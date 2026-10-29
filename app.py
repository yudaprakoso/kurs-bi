"""Streamlit dashboard Kurs Transaksi Bank Indonesia."""
import io
import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from database import init_db, read_all, save_records, DB_PATH
from excel_importer import preview_excel, import_records
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BI_URL = os.getenv("BI_URL", "https://www.bi.go.id/id/statistik/informasi-kurs/transaksi-bi/default.aspx")


def scrape_via_worker(headless: bool):
    """Run Playwright in its own Python process (Windows subprocess-safe)."""
    with tempfile.TemporaryDirectory(prefix="bi_scrape_") as tmp:
        result_file = Path(tmp) / "result.json"
        command = [sys.executable, str(BASE_DIR / "scraper_worker.py"),
                   "--output", str(result_file),
                   "--headless", "true" if headless else "false"]
        proc = subprocess.run(
            command, cwd=str(BASE_DIR), capture_output=True, text=True,
            timeout=180, check=False
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "Unknown worker failure").strip()
            raise RuntimeError(f"Scraper subprocess gagal (exit {proc.returncode}):\n{detail[-4500:]}")
        if not result_file.is_file():
            raise RuntimeError("Worker berhasil tetapi tidak menghasilkan file JSON.")
        data = json.loads(result_file.read_text(encoding="utf-8"))
        if not data.get("records"):
            raise RuntimeError("Worker tidak mengembalikan data kurs.")
        return data["tanggal"], data["records"]

st.set_page_config(page_title="Monitoring Kurs BI", page_icon="💱", layout="wide")
init_db()

st.title("💱 Dashboard Monitoring Kurs Transaksi BI")
st.caption("Data bersumber dari tabel Kurs Transaksi pada situs Bank Indonesia. Snapshot disimpan di SQLite.")

with st.sidebar:
    st.header("⚙️ Sinkronisasi")
    headless = st.toggle("Browser tanpa tampilan (headless)", value=os.getenv("HEADLESS", "false").lower() == "true",
                         help="Nonaktifkan pada Windows/desktop sesuai konfigurasi scraper yang telah berhasil.")
    if st.button("🔄 Ambil dan simpan kurs", type="primary", use_container_width=True):
        with st.spinner("Membuka halaman BI dan membaca tabel kurs..."):
            try:
                tanggal, records = scrape_via_worker(headless=headless)
                count = save_records(records)
                st.success(f"Tersimpan/diperbarui: {count} mata uang untuk tanggal sumber {tanggal}.")
            except Exception as exc:
                st.error(f"Sinkronisasi gagal: {exc}")
                st.info("Scraper berjalan dalam subprocess terpisah untuk kompatibilitas Windows. Bila tetap gagal, jalankan `python scraper_worker.py --output hasil.json --headless false` untuk melihat pesan error di terminal.")
    st.caption(f"Database: `{DB_PATH}`")
    st.caption("Tombol ini mengambil data yang ditampilkan halaman saat ini, bukan otomatis seluruh tanggal lampau.")
    st.markdown(f"[Buka halaman BI]({BI_URL})")

st.subheader("📥 Impor Historis Kurs dari Excel")
with st.expander("Upload Excel (.xlsx) ke database SQLite", expanded=False):
    st.caption("Kolom wajib: Nilai, Kurs Jual, Kurs Beli, Tanggal. Kolom NO diabaikan. Tanggal 1/2/2020 dibaca 2 Januari 2020 (MM/DD/YYYY).")
    upload = st.file_uploader("Pilih file histori kurs", type=["xlsx"], key="historical_upload")
    currency = st.text_input("Kode mata uang untuk file ini", value="USD", max_chars=3).upper().strip()
    replace = st.checkbox("Perbarui data yang sudah ada (default: lewati duplikat)", value=False)
    if upload is not None:
        try:
            if len(currency) != 3 or not currency.isalpha():
                st.error("Kode mata uang harus 3 huruf, misalnya USD.")
            else:
                preview, errors, total = preview_excel(upload, default_currency=currency)
                st.write(f"Dibaca: {total} baris | valid (unik): {len(preview)} | kesalahan: {len(errors)}")
                if not preview.empty:
                    st.dataframe(preview.head(20), hide_index=True, use_container_width=True)
                if not errors.empty:
                    st.warning("Baris berikut tidak akan diimpor. Periksa data Excel sebelum melanjutkan.")
                    st.dataframe(errors, hide_index=True, use_container_width=True)
                if st.button("💾 Simpan hasil Excel ke SQLite", type="primary", disabled=preview.empty):
                    result = import_records(preview, replace_existing=replace)
                    st.success(f"Selesai! Data baru: {result['baru']}; diperbarui: {result['diperbarui']}; dilewati: {result['dilewati']}.")
                    st.rerun()
        except Exception as exc:
            st.error(f"Tidak dapat membaca Excel: {exc}")

df = read_all()
if df.empty:
    st.info("Database masih kosong. Klik **Ambil dan simpan kurs** di panel kiri untuk memulai.")
    st.stop()

df["tanggal_dt"] = pd.to_datetime(df["tanggal"], errors="coerce")
df = df.dropna(subset=["tanggal_dt"])
if df.empty:
    st.warning("Tidak ada tanggal valid di database.")
    st.stop()

min_date, max_date = df["tanggal_dt"].min().date(), df["tanggal_dt"].max().date()
currencies = sorted(df["mata_uang"].unique().tolist())

st.subheader("Filter Data")
f1, f2, f3 = st.columns([1.4, 1.4, 1])
with f1:
    selected_currencies = st.multiselect("Mata uang", currencies, default=["USD"] if "USD" in currencies else currencies[:1])
with f2:
    dates = st.date_input("Periode tanggal", value=(min_date, max_date), min_value=min_date, max_value=max_date)
with f3:
    chosen_metric = st.selectbox("Jenis kurs grafik", ["Kurs Jual", "Kurs Beli", "Kurs Tengah", "Ketiganya"])

if not selected_currencies:
    st.warning("Pilih minimal satu mata uang.")
    st.stop()
if not isinstance(dates, (tuple, list)) or len(dates) != 2:
    st.info("Silakan pilih tanggal awal dan akhir.")
    st.stop()
start, end = dates
if start > end:
    st.error("Tanggal awal tidak boleh lebih besar daripada tanggal akhir.")
    st.stop()
filtered = df[(df["mata_uang"].isin(selected_currencies)) &
              (df["tanggal_dt"].dt.date >= start) &
              (df["tanggal_dt"].dt.date <= end)].copy()
if filtered.empty:
    st.warning("Tidak ada data untuk kombinasi filter tersebut.")
    st.stop()

latest = filtered["tanggal_dt"].max()
latest_rows = filtered[filtered["tanggal_dt"] == latest]
a, b, c, d = st.columns(4)
a.metric("Tanggal data terbaru", latest.strftime("%d-%m-%Y"))
b.metric("Mata uang pada periode", filtered["mata_uang"].nunique())
c.metric("Jumlah catatan", f"{len(filtered):,}")
d.metric("Jumlah tanggal tercatat", filtered["tanggal"].nunique())

st.subheader("Grafik Historis Kurs")
st.caption("Nilai kurs ditampilkan per nominal unit pada kolom 'nilai' dari BI. Perbandingan lintas mata uang perlu mempertimbangkan nominal unit masing-masing.")
chart_cols = {
    "Kurs Jual": ["kurs_jual"],
    "Kurs Beli": ["kurs_beli"],
    "Kurs Tengah": ["kurs_tengah"],
    "Ketiganya": ["kurs_jual", "kurs_beli", "kurs_tengah"],
}[chosen_metric]
chart_df = filtered.sort_values("tanggal_dt").melt(
    id_vars=["tanggal_dt", "mata_uang"], value_vars=chart_cols,
    var_name="jenis", value_name="kurs")
chart_df["seri"] = chart_df["mata_uang"] + " — " + chart_df["jenis"].map({"kurs_jual": "Jual", "kurs_beli": "Beli", "kurs_tengah": "Tengah"})
fig = px.line(chart_df, x="tanggal_dt", y="kurs", color="seri", markers=True,
              labels={"tanggal_dt": "Tanggal", "kurs": "Rupiah (IDR)", "seri": "Seri"})
fig.update_layout(hovermode="x unified", legend_title_text="Mata uang / Kurs")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Kurs Tengah")
st.caption("Kurs Tengah = (Kurs Jual + Kurs Beli) / 2. Nilai mengikuti nominal unit mata uang sebagaimana dipublikasikan BI.")
latest_middle = latest_rows.sort_values("mata_uang")[["mata_uang", "kurs_tengah"]]
st.dataframe(latest_middle, hide_index=True, use_container_width=True,
             column_config={"mata_uang": "Mata Uang",
                            "kurs_tengah": st.column_config.NumberColumn("Kurs Tengah Terbaru (Rp)", format="%.4f")})

st.subheader("Tabel Kurs")
visible = filtered.sort_values(["tanggal", "mata_uang"], ascending=[False, True])[
    ["tanggal", "mata_uang", "nilai", "kurs_jual", "kurs_beli", "kurs_tengah", "waktu_sinkron", "sumber"]]
st.dataframe(visible, use_container_width=True, hide_index=True,
             column_config={"nilai": st.column_config.NumberColumn("Nominal Unit", format="%.2f"),
                            "kurs_jual": st.column_config.NumberColumn("Kurs Jual (Rp)", format="%.2f"),
                            "kurs_beli": st.column_config.NumberColumn("Kurs Beli (Rp)", format="%.2f"),
                            "kurs_tengah": st.column_config.NumberColumn("Kurs Tengah (Rp)", format="%.4f")})

left, right = st.columns(2)
with left:
    csv = visible.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ Unduh CSV", csv, "kurs_bi_terfilter.csv", "text/csv", use_container_width=True)
with right:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        visible.to_excel(writer, sheet_name="Kurs BI", index=False)
        sheet = writer.sheets["Kurs BI"]
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, len(visible), len(visible.columns)-1)
        sheet.set_column("A:A", 13)
        sheet.set_column("B:B", 12)
        sheet.set_column("C:F", 18)
        sheet.set_column("G:G", 22)
        sheet.set_column("H:H", 56)
    st.download_button("⬇️ Unduh Excel", buffer.getvalue(), "kurs_bi_terfilter.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

st.caption("Data historis bertambah ketika sinkronisasi dilakukan pada tanggal yang berbeda. Hari libur atau tanggal tanpa publikasi kurs tidak akan otomatis memiliki catatan.")
