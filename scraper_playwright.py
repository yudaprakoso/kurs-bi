"""Scraper tabel Kurs Transaksi BI. Menjalankan browser lokal; tidak memakai SOAP API."""
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
BI_URL = os.getenv("BI_URL", "https://www.bi.go.id/id/statistik/informasi-kurs/transaksi-bi/default.aspx")

MONTHS = {"januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
          "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
          "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
          "agu": 8, "agt": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12}


def parse_date(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "").strip())
    match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value)
    if match:
        day, month, year = match.groups()
        number = MONTHS.get(month.lower())
        if number:
            return date(int(year), number, int(day)).isoformat()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Tanggal sumber belum dikenali: {value!r}. Penyimpanan dibatalkan untuk mencegah tanggal salah.")


def parse_decimal(value: str) -> float:
    value = re.sub(r"\s+", "", str(value))
    value = value.replace("Rp", "").replace(".", "").replace(",", ".")
    try:
        return float(Decimal(value))
    except InvalidOperation as error:
        raise ValueError(f"Angka kurs tidak valid: {value}") from error


def extract_source_date(page) -> str:
    body_text = page.locator("body").inner_text()
    candidates = [
        r"Update\s+Terakhir\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"(?:Tanggal|Kurs\s+Tanggal)\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ]
    for pattern in candidates:
        match = re.search(pattern, body_text, flags=re.IGNORECASE)
        if match:
            return parse_date(match.group(1))
    raise ValueError("Tanggal kurs tidak ditemukan pada halaman. Periksa tampilan halaman BI sebelum menyimpan.")


def scrape_kurs(headless: bool = False) -> tuple[str, list[dict]]:
    """Ambil snapshot tabel yang *sedang ditampilkan*, tidak mengambil histori otomatis."""
    timeout_ms = int(os.getenv("SCRAPE_TIMEOUT_MS", "60000"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page(locale="id-ID", viewport={"width": 1440, "height": 900})
            page.goto(BI_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            page.get_by_text("USD", exact=True).last.wait_for(state="visible", timeout=timeout_ms)
            tanggal = extract_source_date(page)
            records = []
            tables = page.locator("table")
            for i in range(tables.count()):
                table = tables.nth(i)
                headers = table.inner_text().lower()
                if not all(word in headers for word in ("mata uang", "kurs jual", "kurs beli")):
                    continue
                rows = table.locator("tr")
                for j in range(rows.count()):
                    cells = rows.nth(j).locator("td")
                    if cells.count() < 4:
                        continue
                    values = [cells.nth(k).inner_text().strip() for k in range(4)]
                    currency = values[0].upper()
                    if not re.fullmatch(r"[A-Z]{3}", currency):
                        continue
                    try:
                        record = {"tanggal": tanggal, "mata_uang": currency,
                                  "nilai": parse_decimal(values[1]),
                                  "kurs_jual": parse_decimal(values[2]),
                                  "kurs_beli": parse_decimal(values[3]), "sumber": BI_URL}
                        if record["nilai"] > 0 and record["kurs_jual"] > 0 and record["kurs_beli"] > 0:
                            records.append(record)
                    except ValueError:
                        continue
                if records:
                    break
            if not records:
                diagnostic = Path("data/debug_bi.html")
                diagnostic.parent.mkdir(parents=True, exist_ok=True)
                diagnostic.write_text(page.content(), encoding="utf-8")
                raise RuntimeError("Tabel kurs tidak terbaca. HTML diagnostik: data/debug_bi.html")
            unique = {r["mata_uang"]: r for r in records}
            return tanggal, list(unique.values())
        finally:
            browser.close()
