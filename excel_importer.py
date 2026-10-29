"""Impor laporan kurs BI XLSX ke skema kurs_bi yang digunakan dashboard."""
from __future__ import annotations
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
import pandas as pd
from database import connect, init_db

REQUIRED = {"nilai", "kurs_jual", "kurs_beli", "tanggal"}


def normalize_header(value):
    text = re.sub(r"\s+", " ", str(value).strip().lower())
    aliases = {"no": "no", "nomor": "no", "nilai": "nilai",
               "kurs jual": "kurs_jual", "kurs_beli": "kurs_beli",
               "kurs beli": "kurs_beli", "kurs_jual": "kurs_jual",
               "tanggal": "tanggal", "mata uang": "mata_uang", "mata_uang": "mata_uang"}
    return aliases.get(text, text)


def parse_id_decimal(value):
    if pd.isna(value) or str(value).strip() == "":
        raise ValueError("angka kosong")
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = Decimal(str(value))
    else:
        text = str(value).strip().replace("Rp", "").replace("rp", "").replace(" ", "")
        # 13.964,48 => 13964.48; 1,00 => 1.00
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        elif text.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
            text = text.replace(".", "")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"angka tidak valid: {value}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("angka harus positif")
    return float(number)


def parse_us_date(value):
    if pd.isna(value):
        raise ValueError("tanggal kosong")
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    # Bentuk ekspor BI: 1/2/2020 12:00:00 AM = 2 Januari 2020, bukan 1 Februari.
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"tanggal tidak valid: {value!r}")


def preview_excel(file, default_currency="USD", sheet_name=0):
    df = pd.read_excel(file, sheet_name=sheet_name, engine="openpyxl", dtype=object)
    df.columns = [normalize_header(c) for c in df.columns]
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError("Kolom Excel tidak ditemukan: " + ", ".join(sorted(missing)))
    records, errors = [], []
    for index, row in df.iterrows():
        if row[list(REQUIRED)].isna().all():
            continue
        try:
            currency = row.get("mata_uang", default_currency)
            if pd.isna(currency) or not str(currency).strip():
                currency = default_currency
            currency = str(currency).strip().upper()
            if not re.fullmatch("[A-Z]{3}", currency):
                raise ValueError("kode mata uang harus 3 huruf")
            tanggal = parse_us_date(row["tanggal"])
            nilai = parse_id_decimal(row["nilai"])
            jual = parse_id_decimal(row["kurs_jual"])
            beli = parse_id_decimal(row["kurs_beli"])
            if jual < beli:
                raise ValueError("kurs jual lebih kecil dari kurs beli")
            records.append({"tanggal": tanggal, "mata_uang": currency,
                            "nilai": nilai, "kurs_jual": jual, "kurs_beli": beli,
                            "kurs_tengah": round((jual + beli) / 2, 4), "sumber": "IMPORT_EXCEL"})
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"baris_excel": int(index) + 2, "masalah": str(exc)})
    clean = pd.DataFrame(records, columns=["tanggal", "mata_uang", "nilai", "kurs_jual", "kurs_beli", "kurs_tengah", "sumber"])
    if not clean.empty:
        clean = clean.drop_duplicates(subset=["tanggal", "mata_uang"], keep="last")
    return clean, pd.DataFrame(errors, columns=["baris_excel", "masalah"]), len(df)


def import_records(preview_df: pd.DataFrame, replace_existing=False):
    if preview_df.empty:
        return {"baru": 0, "dilewati": 0, "diperbarui": 0}
    init_db()
    rows = list(preview_df.to_dict("records"))
    n_new = n_skip = n_update = 0
    with connect() as db:
        for row in rows:
            exists = db.execute("SELECT 1 FROM kurs_bi WHERE tanggal=? AND mata_uang=?", (row["tanggal"], row["mata_uang"])).fetchone()
            if exists and not replace_existing:
                n_skip += 1
                continue
            if exists:
                db.execute("""UPDATE kurs_bi SET nilai=:nilai, kurs_jual=:kurs_jual,
                           kurs_beli=:kurs_beli, kurs_tengah=:kurs_tengah, sumber=:sumber,
                           waktu_sinkron=datetime('now','localtime')
                           WHERE tanggal=:tanggal AND mata_uang=:mata_uang""", row)
                n_update += 1
            else:
                db.execute("""INSERT INTO kurs_bi
                    (tanggal,mata_uang,nilai,kurs_jual,kurs_beli,kurs_tengah,sumber)
                    VALUES (:tanggal,:mata_uang,:nilai,:kurs_jual,:kurs_beli,:kurs_tengah,:sumber)""", row)
                n_new += 1
        db.commit()
    return {"baru": n_new, "dilewati": n_skip, "diperbarui": n_update}
