"""Scraper tabel Kurs Transaksi BI menggunakan Chromium Playwright."""

import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import (
    Error as PlaywrightError,
    sync_playwright,
)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BI_URL = os.getenv(
    "BI_URL",
    "https://www.bi.go.id/id/statistik/informasi-kurs/"
    "transaksi-bi/default.aspx",
)

MONTHS = {
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "agu": 8,
    "agt": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "des": 12,
}


def parse_date(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "").strip())

    match = re.search(
        r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
        value,
    )

    if match:
        day, month, year = match.groups()
        month_number = MONTHS.get(month.lower())

        if month_number:
            return date(
                int(year),
                month_number,
                int(day),
            ).isoformat()

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    raise ValueError(
        f"Tanggal sumber belum dikenali: {value!r}. "
        "Penyimpanan dibatalkan untuk mencegah tanggal salah."
    )


def parse_decimal(value: str) -> float:
    """Konversi format Indonesia: 16.500,25 menjadi 16500.25."""
    value = re.sub(r"\s+", "", str(value))
    value = value.replace("Rp", "")
    value = value.replace(".", "").replace(",", ".")

    try:
        number = Decimal(value)

        if not number.is_finite():
            raise ValueError(f"Angka kurs tidak valid: {value}")

        return float(number)

    except InvalidOperation as exc:
        raise ValueError(
            f"Angka kurs tidak valid: {value}"
        ) from exc


def extract_source_date(page) -> str:
    body_text = page.locator("body").inner_text()

    patterns = [
        r"Update\s+Terakhir\s*:?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"(?:Tanggal|Kurs\s+Tanggal)\s*:?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            body_text,
            flags=re.IGNORECASE,
        )

        if match:
            return parse_date(match.group(1))

    raise ValueError(
        "Tanggal kurs tidak ditemukan pada halaman. "
        "Periksa tampilan halaman BI sebelum menyimpan."
    )


def ensure_chromium(playwright):
    """Download Chromium Playwright jika belum tersedia."""
    executable = Path(playwright.chromium.executable_path)

    if executable.is_file():
        return

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    if result.returncode != 0:
        detail = (
            result.stderr
            or result.stdout
            or "Tidak ada detail instalasi."
        ).strip()

        raise RuntimeError(
            f"Instalasi Chromium gagal:\n{detail[-3000:]}"
        )

    if not executable.is_file():
        raise RuntimeError(
            "Executable Chromium belum ditemukan di: "
            f"{executable}"
        )


def open_bi_page(page, timeout_ms: int):
    """Coba kembali maksimal 3 kali jika koneksi di-reset."""
    for attempt in range(3):
        try:
            response = page.goto(
                BI_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            if response is not None and response.status >= 400:
                raise RuntimeError(
                    f"Halaman BI mengembalikan HTTP {response.status}."
                )

            return

        except PlaywrightError as exc:
            if "ERR_CONNECTION_RESET" not in str(exc):
                raise

            if attempt == 2:
                raise RuntimeError(
                    "Koneksi dari server aplikasi ke BI diputus "
                    "setelah 3 percobaan (ERR_CONNECTION_RESET). "
                    "Retry tidak berhasil memulihkan koneksi."
                ) from exc

            time.sleep(3)


def scrape_kurs(
    headless: bool = True,
) -> tuple[str, list[dict]]:
    """Ambil snapshot tabel saat ini, bukan histori otomatis."""
    timeout_ms = int(
        os.getenv("SCRAPE_TIMEOUT_MS", "60000")
    )

    with sync_playwright() as p:
        ensure_chromium(p)

        # Selalu headless agar dapat berjalan di Streamlit Cloud.
        # Parameter fungsi tetap tersedia agar kompatibel dengan worker.
        browser = p.chromium.launch(
            headless=headless,
            timeout=timeout_ms,
        )

        try:
            page = browser.new_page(
                locale="id-ID",
                viewport={
                    "width": 1440,
                    "height": 900,
                },
            )

            page.set_default_timeout(timeout_ms)

            open_bi_page(page, timeout_ms)

            page.get_by_text(
                "USD",
                exact=True,
            ).last.wait_for(
                state="visible",
                timeout=timeout_ms,
            )

            tanggal = extract_source_date(page)
            records = []

            tables = page.locator("table")

            for i in range(tables.count()):
                table = tables.nth(i)

                headers = re.sub(
                    r"\s+",
                    " ",
                    table.inner_text().lower(),
                )

                required_headers = (
                    "mata uang",
                    "kurs jual",
                    "kurs beli",
                )

                if not all(
                    header in headers
                    for header in required_headers
                ):
                    continue

                rows = table.locator("tr")

                for j in range(rows.count()):
                    cells = rows.nth(j).locator("td")

                    if cells.count() < 4:
                        continue

                    values = [
                        cells.nth(k).inner_text().strip()
                        for k in range(4)
                    ]

                    currency = values[0].upper()

                    if not re.fullmatch(r"[A-Z]{3}", currency):
                        continue

                    try:
                        record = {
                            "tanggal": tanggal,
                            "mata_uang": currency,
                            "nilai": parse_decimal(values[1]),
                            "kurs_jual": parse_decimal(values[2]),
                            "kurs_beli": parse_decimal(values[3]),
                            "sumber": BI_URL,
                        }

                        if all(
                            record[column] > 0
                            for column in (
                                "nilai",
                                "kurs_jual",
                                "kurs_beli",
                            )
                        ):
                            records.append(record)

                    except ValueError:
                        continue

                if records:
                    break

            if not records:
                diagnostic = BASE_DIR / "data" / "debug_bi.html"

                diagnostic.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                diagnostic.write_text(
                    page.content(),
                    encoding="utf-8",
                )

                raise RuntimeError(
                    "Tabel kurs tidak terbaca. "
                    f"HTML diagnostik: {diagnostic}"
                )

            unique = {
                record["mata_uang"]: record
                for record in records
            }

            return tanggal, list(unique.values())

        finally:
            browser.close()
