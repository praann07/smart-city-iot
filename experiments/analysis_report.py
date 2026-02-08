"""Generate basic experiment metrics and plots from backend/db/iot.db."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "db" / "iot.db"
OUT_DIR = Path(__file__).resolve().parent / "results"


def fetch_rows() -> List[sqlite3.Row]:
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  cur = conn.execute(
      """
      SELECT node_id, pm25, temp_tenths, noise_db, battery_mv, seq, node_ts, recv_ts
      FROM readings
      ORDER BY recv_ts ASC
      """
  )
  rows = cur.fetchall()
  conn.close()
  return rows


def compute_summary(rows: List[sqlite3.Row]) -> List[Dict[str, float]]:
  per_node: Dict[str, Dict[str, float]] = {}
  for r in rows:
    node = r["node_id"]
    info = per_node.setdefault(
        node,
        {
            "count": 0.0,
            "seq_min": float("inf"),
            "seq_max": float("-inf"),
            "pm25_sum": 0.0,
            "pm25_cnt": 0.0,
            "temp_sum": 0.0,
            "temp_cnt": 0.0,
            "noise_sum": 0.0,
            "noise_cnt": 0.0,
        },
    )
    info["count"] += 1
    seq = r["seq"]
    if seq is not None:
      info["seq_min"] = min(info["seq_min"], seq)
      info["seq_max"] = max(info["seq_max"], seq)
    if r["pm25"] is not None:
      info["pm25_sum"] += r["pm25"]
      info["pm25_cnt"] += 1
    if r["temp_tenths"] is not None:
      info["temp_sum"] += r["temp_tenths"]
      info["temp_cnt"] += 1
    if r["noise_db"] is not None:
      info["noise_sum"] += r["noise_db"]
      info["noise_cnt"] += 1

  summary = []
  for node, info in per_node.items():
    expected = 0.0
    if info["seq_min"] != float("inf") and info["seq_max"] != float("-inf"):
      expected = info["seq_max"] - info["seq_min"] + 1
    loss_rate = 0.0
    if expected > 0:
      loss_rate = max(0.0, 1.0 - (info["count"] / expected))
    summary.append(
        {
            "node_id": node,
            "count": int(info["count"]),
            "expected": int(expected),
            "loss_rate": round(loss_rate, 4),
            "avg_pm25": round(info["pm25_sum"] / info["pm25_cnt"], 2) if info["pm25_cnt"] else None,
            "avg_temp_tenths": round(info["temp_sum"] / info["temp_cnt"], 2) if info["temp_cnt"] else None,
            "avg_noise_db": round(info["noise_sum"] / info["noise_cnt"], 2) if info["noise_cnt"] else None,
        }
    )
  return sorted(summary, key=lambda x: x["node_id"])


def write_csv(summary: List[Dict[str, float]]) -> Path:
  OUT_DIR.mkdir(parents=True, exist_ok=True)
  path = OUT_DIR / "node_summary.csv"
  with path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "node_id",
            "count",
            "expected",
            "loss_rate",
            "avg_pm25",
            "avg_temp_tenths",
            "avg_noise_db",
        ],
    )
    writer.writeheader()
    writer.writerows(summary)
  return path


def plot_counts(summary: List[Dict[str, float]]) -> Path:
  nodes = [row["node_id"] for row in summary]
  counts = [row["count"] for row in summary]
  plt.figure(figsize=(12, 5))
  plt.bar(nodes, counts, color="#4C78A8")
  plt.title("Packets Collected per Node")
  plt.xlabel("Node")
  plt.ylabel("Packet Count")
  plt.xticks(rotation=60, ha="right")
  plt.tight_layout()
  out = OUT_DIR / "packets_per_node.png"
  plt.savefig(out, dpi=150)
  plt.close()
  return out


def plot_loss(summary: List[Dict[str, float]]) -> Path:
  nodes = [row["node_id"] for row in summary]
  loss = [row["loss_rate"] for row in summary]
  plt.figure(figsize=(12, 5))
  plt.bar(nodes, loss, color="#F58518")
  plt.title("Estimated Packet Loss Rate per Node")
  plt.xlabel("Node")
  plt.ylabel("Loss Rate")
  plt.xticks(rotation=60, ha="right")
  plt.tight_layout()
  out = OUT_DIR / "loss_rate_per_node.png"
  plt.savefig(out, dpi=150)
  plt.close()
  return out


def plot_time_series(rows: List[sqlite3.Row]) -> Path:
  # Pick one example node (most samples) and plot pm25/temperature/noise
  counts: Dict[str, int] = {}
  for r in rows:
    counts[r["node_id"]] = counts.get(r["node_id"], 0) + 1
  node = max(counts.items(), key=lambda x: x[1])[0]

  ts = []
  pm = []
  temp = []
  noise = []
  for r in rows:
    if r["node_id"] != node:
      continue
    ts.append(r["recv_ts"])
    pm.append(r["pm25"] if r["pm25"] is not None else float("nan"))
    temp.append((r["temp_tenths"] / 10.0) if r["temp_tenths"] is not None else float("nan"))
    noise.append(r["noise_db"] if r["noise_db"] is not None else float("nan"))

  plt.figure(figsize=(12, 6))
  plt.plot(ts, pm, label="PM2.5")
  plt.plot(ts, temp, label="Temperature (°C)")
  plt.plot(ts, noise, label="Noise (dB)")
  plt.title(f"Time Series for {node}")
  plt.xlabel("Receive Time")
  plt.ylabel("Value")
  plt.legend()
  plt.tight_layout()
  out = OUT_DIR / "timeseries_example.png"
  plt.savefig(out, dpi=150)
  plt.close()
  return out


def main() -> None:
  rows = fetch_rows()
  if not rows:
    raise SystemExit("No readings in database. Run collector/simulation first.")
  summary = compute_summary(rows)
  csv_path = write_csv(summary)
  plots = [plot_counts(summary), plot_loss(summary), plot_time_series(rows)]
  print(f"Wrote summary: {csv_path}")
  for p in plots:
    print(f"Wrote plot: {p}")


if __name__ == "__main__":
  main()
