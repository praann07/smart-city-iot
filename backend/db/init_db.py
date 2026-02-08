from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent / "iot.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

def main():
  conn = sqlite3.connect(DB_PATH)
  with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    conn.executescript(f.read())
  conn.commit()
  conn.close()
  print(f"initialized {DB_PATH}")


if __name__ == "__main__":
  main()
