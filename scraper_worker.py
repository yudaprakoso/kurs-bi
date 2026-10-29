"""Dedicated Playwright worker. Run separately from the Streamlit event loop."""
import argparse
import json
import sys
import traceback
from pathlib import Path

from scraper_playwright import scrape_kurs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--headless", choices=["true", "false"], default="false")
    args = parser.parse_args()
    try:
        tanggal, records = scrape_kurs(headless=(args.headless == "true"))
        if not records:
            raise ValueError("BI tidak mengembalikan baris kurs.")
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"tanggal": tanggal, "records": records}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
