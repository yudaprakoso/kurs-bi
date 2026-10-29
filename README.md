# Dashboard Monitoring Kurs BI

Aplikasi Python Streamlit dengan scraper Playwright (`HEADLESS=false`), SQLite, filter mata uang & tanggal, grafik Plotly, dan ekspor CSV/Excel.

## Instalasi

1. Python 3.10+ disarankan.
2. Buat virtualenv (opsional): `python -m venv .venv`.
3. Aktifkan virtualenv pada Windows: `.venv\Scripts\activate` (PowerShell: `.venv\Scripts\Activate.ps1`).
4. `pip install -r requirements.txt`
5. `python -m playwright install chromium`
6. Salin `.env.example` menjadi `.env`; pertahankan `HEADLESS=false` pada desktop yang sudah berhasil menjalankan Playwright.
7. `streamlit run app.py`
8. Buka alamat Streamlit yang tercetak di terminal, tekan **Ambil dan simpan kurs**.

## Perbaikan Windows NotImplementedError

Versi ini menjalankan Playwright di `scraper_worker.py` sebagai proses terpisah dari Streamlit. Event loop Streamlit di Windows tidak lagi dipakai untuk membuat subprocess Chromium.

Untuk debug jalankan `python scraper_worker.py --output hasil.json --headless false`. Jalankan dari environment Conda yang sama dengan `streamlit run app.py`.

Jangan menghapus `data/kurs_bi.sqlite3` ketika memperbarui berkas aplikasi jika ingin menjaga histori.

## Cara kerja

- Klik sinkronisasi: browser Playwright membuka halaman Kurs Transaksi BI dan mengambil snapshot tabel yang sedang tampil.
- Aplikasi membaca tanggal yang tertulis pada halaman, lalu menyimpan data ke `data/kurs_bi.sqlite3`.
- Kunci unik `(tanggal, mata_uang)` mencegah duplikasi saat sinkronisasi diulang.
- Data historis hanya ada untuk tanggal yang telah benar-benar tersimpan. Aplikasi **belum** mengoperasikan filter rentang tanggal BI secara otomatis.
- Spreadsheet Excel dan CSV yang diunduh mengikuti filter dashboard.

## Catatan penting

- Uji pada Windows dengan sesi desktop aktif untuk `HEADLESS=false`.
- Playwright/selector dapat perlu penyesuaian jika HTML halaman BI berubah.
- Bila Chrome muncul tetapi tidak ada tabel: periksa `data/debug_bi.html`, dan jalankan scraper lama Anda yang sudah berhasil untuk membandingkan selector.
- Tanggal sumber harus terbaca; jika tidak, operasi batal agar data tidak dilabeli tanggal yang salah.
- Jaga intensitas scraping wajar serta patuhi ketentuan akses situs BI.
- Jangan akses dashboard tanpa autentikasi dari Internet publik karena tombol scraping mengendalikan browser server.

## Kurs Tengah (versi terbaru)

- Rumus: `kurs_tengah = (kurs_jual + kurs_beli) / 2`.
- Ditampilkan pada ringkasan, tabel dan opsi grafik **Kurs Tengah** / **Ketiganya**.
- Termasuk kolom ekspor CSV/Excel.
- Saat aplikasi dimulai, `init_db()` menambahkan kolom `kurs_tengah` bila belum ada dan menghitung ulang seluruh data historis lama. **Jangan hapus database lama.**
- Data tetap mengikuti `nilai` unit mata uang dari tabel BI (misalnya JPY dapat direpresentasikan per 100 unit).

## Impor histori kurs dari Excel (.xlsx)

1. Jalankan `pip install -r requirements.txt`, lalu `python -m streamlit run app.py`.
2. Buka panel **📥 Impor Historis Kurs dari Excel** di dashboard.
3. Upload `.xlsx` dengan header `NO | Nilai | Kurs Jual | Kurs Beli | Tanggal`.
4. Pilih mata uang `USD` (default) dan periksa pratinjau serta daftar baris bermasalah.
5. Klik **💾 Simpan hasil Excel ke SQLite**. Default akan **melewati data yang sudah ada**; centang opsi perbarui bila ingin menimpa nilai historis.
6. Grafik dashboard langsung membaca SQLite. File Excel tidak menghapus data yang telah ada.

**Format tanggal:** `1/2/2020 12:00:00 AM` adalah **2 Januari 2020** (`MM/DD/YYYY`), bukan 1 Februari. Tanggal disimpan dalam ISO `2020-01-02`.

**Format rupiah:** `13.964,48` menjadi numerik `13964.48`; Kurs Tengah otomatis `(jual + beli)/2`.

**Pencadangan:** sebelum impor dalam jumlah besar, cadangkan file `data/kurs_bi.sqlite3` saat aplikasi tidak sedang menulis ke database.

**Catatan:** Jika file Excel berisi tanggal `DD/MM/YYYY` alih-alih `MM/DD/YYYY`, ubah fungsi `parse_us_date()` agar format tanggal benar. Impor menggunakan sheet pertama dalam workbook.
