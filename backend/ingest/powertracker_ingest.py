"""Load Cooja PowerTracker CSV exports into energy_samples.

- Flexible header detection (CPU/LPM/Tx/Rx/Battery/Time/Node ID)
- Accepts comma/semicolon/tab delimiters; can override explicitly.
- Inserts into SQLite (backend/db/iot.db by default).

Usage examples:
  python backend/ingest/powertracker_ingest.py powertracker.csv
  python backend/ingest/powertracker_ingest.py powertracker.csv --db backend/db/iot.db --preview 5
  python backend/ingest/powertracker_ingest.py powertracker.csv --node-col mote --delimiter ';'
"""

import argparse
import csv
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DB_DEFAULT = Path(__file__).resolve().parents[1] / "db" / "iot.db"

# Heuristics for matching column names (lowercased)
FIELD_HINTS = {
    "node_id": ("id", "node", "mote"),
    "cpu_ms": ("cpu",),
    "lpm_ms": ("lpm", "lowpower"),
    "tx_ms": ("tx", "transmit"),
    "rx_ms": ("rx", "listen", "receive"),
    "battery_mv": ("batt", "volt"),
    "node_ts": ("time", "timestamp", "sec"),
}


def detect_delimiter(sample: str, fallback: str = ",") -> str:
  try:
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    return dialect.delimiter
  except Exception:
    return fallback


def detect_columns(header: List[str], overrides: Dict[str, Optional[str]]) -> Dict[str, int]:
  normalized = [h.strip().lower() for h in header]
  mapping: Dict[str, int] = {}

  # Apply explicit overrides first
  for field, name in overrides.items():
    if name:
      try:
        mapping[field] = normalized.index(name.strip().lower())
      except ValueError as exc:
        raise ValueError(f"Override column '{name}' for {field} not found in header {header}") from exc

  # Heuristic detection
  for field, hints in FIELD_HINTS.items():
    if field in mapping:
      continue
    for idx, col in enumerate(normalized):
      if any(h in col for h in hints):
        mapping[field] = idx
        break

  missing = [f for f in ("node_id", "cpu_ms", "lpm_ms", "tx_ms", "rx_ms") if f not in mapping]
  if missing:
    raise ValueError(f"Missing required columns: {missing}. Header seen: {header}")

  return mapping


def coerce_number(val: str) -> Optional[float]:
  if val is None:
    return None
  txt = str(val).strip().replace(",", "")
  if txt == "":
    return None
  try:
    return float(txt)
  except ValueError:
    return None


def parse_rows(path: Path, delimiter: Optional[str], overrides: Dict[str, Optional[str]]) -> List[Dict[str, Optional[float]]]:
  with path.open("r", encoding="utf-8") as f:
    sample = f.read(1024)
    f.seek(0)
    delim = delimiter or detect_delimiter(sample)
    reader = csv.reader(f, delimiter=delim)
    header = next(reader, None)
    if not header:
      raise ValueError("Empty file or missing header row")

    mapping = detect_columns(header, overrides)
    rows: List[Dict[str, Optional[float]]] = []
    for row in reader:
      if not row or all(not cell.strip() for cell in row):
        continue
      def get(field: str) -> Optional[str]:
        idx = mapping.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

      parsed = {
          "node_id": (get("node_id") or "unknown").strip(),
          "cpu_ms": coerce_number(get("cpu_ms")),
          "lpm_ms": coerce_number(get("lpm_ms")),
          "tx_ms": coerce_number(get("tx_ms")),
          "rx_ms": coerce_number(get("rx_ms")),
          "battery_mv": coerce_number(get("battery_mv")),
          "node_ts": coerce_number(get("node_ts")),
      }
      rows.append(parsed)
  return rows


def insert_rows(db_path: Path, rows: List[Dict[str, Optional[float]]]) -> int:
  if not rows:
    return 0
  conn = sqlite3.connect(db_path)
  cur = conn.cursor()
  now = int(time.time())
  cur.executemany(
      """
      INSERT INTO energy_samples(node_id, cpu_ms, lpm_ms, tx_ms, rx_ms, battery_mv, node_ts, recv_ts)
      VALUES (:node_id, :cpu_ms, :lpm_ms, :tx_ms, :rx_ms, :battery_mv, :node_ts, :recv_ts)
      """,
      [{**row, "recv_ts": now} for row in rows],
  )
  conn.commit()
  conn.close()
  return len(rows)


def main():
  parser = argparse.ArgumentParser(description="Ingest PowerTracker CSV into energy_samples")
  parser.add_argument("csv", type=Path, help="PowerTracker export file")
  parser.add_argument("--db", type=Path, default=DB_DEFAULT, help="SQLite DB path (default backend/db/iot.db)")
  parser.add_argument("--delimiter", help="Force delimiter (default: auto-detect)")
  parser.add_argument("--preview", type=int, default=0, help="Print first N parsed rows and exit")
  parser.add_argument("--node-col")
  parser.add_argument("--cpu-col")
  parser.add_argument("--lpm-col")
  parser.add_argument("--tx-col")
  parser.add_argument("--rx-col")
  parser.add_argument("--battery-col")
  parser.add_argument("--time-col")
  args = parser.parse_args()

  overrides = {
      "node_id": args.node_col,
      "cpu_ms": args.cpu_col,
      "lpm_ms": args.lpm_col,
      "tx_ms": args.tx_col,
      "rx_ms": args.rx_col,
      "battery_mv": args.battery_col,
      "node_ts": args.time_col,
  }

  rows = parse_rows(args.csv, args.delimiter, overrides)
  if args.preview:
    for r in rows[: args.preview]:
      print(r)
    print(f"Previewed {min(args.preview, len(rows))} of {len(rows)} rows. No DB writes performed.")
    return

  inserted = insert_rows(args.db, rows)
  print(f"Inserted {inserted} rows into {args.db}")


if __name__ == "__main__":
  main()
