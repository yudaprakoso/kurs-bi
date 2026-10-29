"""Akses SQLite; satu baris untuk setiap tanggal + mata uang."""
import os
import sqlite3
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
DB_PATH = Path(os.getenv("SQLITE_PATH", "data/kurs_bi.sqlite3"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS kurs_bi (
            tanggal TEXT NOT NULL,
            mata_uang TEXT NOT NULL,
            nilai REAL NOT NULL,
            kurs_jual REAL NOT NULL,
            kurs_beli REAL NOT NULL,
            kurs_tengah REAL,
            sumber TEXT NOT NULL,
            waktu_sinkron TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (tanggal, mata_uang)
        )""")
        # Migrasi non-destruktif untuk database dari versi terdahulu.
        columns = {row[1] for row in db.execute("PRAGMA table_info(kurs_bi)")}
        if "kurs_tengah" not in columns:
            db.execute("ALTER TABLE kurs_bi ADD COLUMN kurs_tengah REAL")
        # Backfill seluruh histori lama, sekaligus jaga konsistensi rumus.
        db.execute("""UPDATE kurs_bi
            SET kurs_tengah = ROUND((kurs_jual + kurs_beli) / 2.0, 4)
            WHERE kurs_tengah IS NULL
               OR ABS(kurs_tengah - (kurs_jual + kurs_beli) / 2.0) > 0.00001""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_kurs_tanggal ON kurs_bi(tanggal)")
        db.commit()


def save_records(records: list[dict]) -> int:
    if not records:
        return 0
    normalized = []
    for record in records:
        entry = dict(record)
        entry["kurs_tengah"] = round((float(entry["kurs_jual"]) + float(entry["kurs_beli"])) / 2, 4)
        normalized.append(entry)
    query = """INSERT INTO kurs_bi(tanggal,mata_uang,nilai,kurs_jual,kurs_beli,kurs_tengah,sumber)
       VALUES(:tanggal,:mata_uang,:nilai,:kurs_jual,:kurs_beli,:kurs_tengah,:sumber)
       ON CONFLICT(tanggal,mata_uang) DO UPDATE SET
       nilai=excluded.nilai, kurs_jual=excluded.kurs_jual,
       kurs_beli=excluded.kurs_beli, kurs_tengah=excluded.kurs_tengah,
       sumber=excluded.sumber,
       waktu_sinkron=datetime('now','localtime')"""
    with connect() as db:
        db.executemany(query, normalized)
        db.commit()
    return len(records)


def read_all() -> pd.DataFrame:
    with connect() as db:
        return pd.read_sql_query("""SELECT tanggal,mata_uang,nilai,kurs_jual,kurs_beli,kurs_tengah,sumber,waktu_sinkron
            FROM kurs_bi ORDER BY tanggal DESC, mata_uang ASC""", db)
