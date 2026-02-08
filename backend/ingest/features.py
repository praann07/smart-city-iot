import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "iot.db"


@dataclass
class FeatureRow:
  node_id: str
  window_start: int
  window_end: int
  count: int
  avg_pm25: Optional[float]
  avg_temp_tenths: Optional[float]
  avg_noise_db: Optional[float]
  battery_drop_per_pkt: Optional[float]
  packet_loss_rate: Optional[float]
  parent_switches: Optional[int]


def compute_features(window_seconds: int = 300) -> List[FeatureRow]:
  conn = sqlite3.connect(DB_PATH)
  cur = conn.cursor()
  cur.execute(
      """
      SELECT node_id, (recv_ts / ?) * ? AS win,
             COUNT(*) AS cnt,
             AVG(pm25), AVG(temp_tenths), AVG(noise_db),
             (MAX(battery_mv) - MIN(battery_mv)) * 1.0 / MAX(COUNT(*), 1),
             MIN(seq), MAX(seq),
             GROUP_CONCAT(parent, ',')
      FROM readings
      GROUP BY node_id, win
      ORDER BY node_id, win;
      """, (window_seconds, window_seconds))

  rows: List[FeatureRow] = []
  for node_id, win, cnt, avg_pm, avg_temp, avg_noise, drop, seq_min, seq_max, parents in cur.fetchall():
    expected = (seq_max - seq_min + 1) if (seq_min is not None and seq_max is not None) else 0
    loss_rate = None
    if expected and expected > 0:
      loss_rate = 1.0 - (cnt * 1.0 / expected)
    parent_switches = 0
    if parents:
      parts = parents.split(',')
      for i in range(1, len(parts)):
        if parts[i] != parts[i-1]:
          parent_switches += 1
    rows.append(
        FeatureRow(
            node_id=node_id,
            window_start=int(win),
            window_end=int(win + window_seconds),
            count=int(cnt),
            avg_pm25=avg_pm,
            avg_temp_tenths=avg_temp,
            avg_noise_db=avg_noise,
            battery_drop_per_pkt=drop,
            packet_loss_rate=loss_rate,
            parent_switches=parent_switches,
        ))
  conn.close()
  return rows


if __name__ == "__main__":
  feats = compute_features()
  for row in feats:
    print(row)
