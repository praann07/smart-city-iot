#!/usr/bin/env python3
"""Live monitor — shows real-time stats updating as simulation runs.

Run this AFTER collector is receiving data. It refreshes every 3 seconds.
"""

import sqlite3
import time
import os
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "db" / "iot.db"

CYAN    = "\033[0;36m"
GREEN   = "\033[0;32m"
YELLOW  = "\033[1;33m"
RED     = "\033[0;31m"
BOLD    = "\033[1m"
NC      = "\033[0m"

def clear():
    os.system("clear")

def run():
    prev_count = 0
    while True:
        try:
            db = sqlite3.connect(DB_PATH)
            db.row_factory = sqlite3.Row

            total = db.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            nodes = db.execute("SELECT COUNT(DISTINCT node_id) FROM readings").fetchone()[0]
            energy = db.execute("SELECT COUNT(*) FROM energy_samples").fetchone()[0]
            batt_min, batt_max = db.execute("SELECT MIN(battery_mv), MAX(battery_mv) FROM readings").fetchone()

            # New packets since last check
            new_packets = total - prev_count
            prev_count = total

            # Latest 5 readings
            latest = db.execute(
                "SELECT node_id, pm25, temp_tenths, noise_db, battery_mv, parent, rank "
                "FROM readings ORDER BY recv_ts DESC LIMIT 5"
            ).fetchall()

            # Per-type counts
            poll_count = db.execute("SELECT COUNT(*) FROM readings WHERE node_id LIKE 'poll_%'").fetchone()[0]
            temp_count = db.execute("SELECT COUNT(*) FROM readings WHERE node_id LIKE 'temp_%'").fetchone()[0]
            noise_count = db.execute("SELECT COUNT(*) FROM readings WHERE node_id LIKE 'noise_%'").fetchone()[0]

            # Nodes with low battery
            low_batt = db.execute(
                "SELECT node_id, MIN(battery_mv) as min_batt FROM readings "
                "GROUP BY node_id HAVING min_batt < 2500 ORDER BY min_batt"
            ).fetchall()

            db.close()

            # ── Display ──
            clear()
            print(f"{CYAN}╔══════════════════════════════════════════════════════════════╗{NC}")
            print(f"{CYAN}║  🏙  SMART CITY IoT — LIVE MONITOR                          ║{NC}")
            print(f"{CYAN}╚══════════════════════════════════════════════════════════════╝{NC}")
            print()
            print(f"  {BOLD}Total Readings:{NC}  {GREEN}{total}{NC}    (+{new_packets} new)")
            print(f"  {BOLD}Active Nodes:{NC}    {GREEN}{nodes}{NC}")
            print(f"  {BOLD}Energy Samples:{NC}  {GREEN}{energy}{NC}")
            print(f"  {BOLD}Battery Range:{NC}   {batt_min} — {batt_max} mV")
            print()
            print(f"  {BOLD}By Sensor Type:{NC}")
            print(f"    Pollution (PM2.5): {poll_count}")
            print(f"    Temperature:       {temp_count}")
            print(f"    Noise (dB):        {noise_count}")

            if low_batt:
                print()
                print(f"  {RED}{BOLD}⚠ Low Battery Nodes:{NC}")
                for r in low_batt:
                    print(f"    {RED}• {r['node_id']}: {r['min_batt']} mV{NC}")

            print()
            print(f"  {YELLOW}{BOLD}Latest Packets:{NC}")
            print(f"  {'Node':<12} {'PM2.5':>6} {'Temp':>6} {'Noise':>6} {'Battery':>8} {'Parent':>8} {'Rank':>5}")
            print(f"  {'─'*12} {'─'*6} {'─'*6} {'─'*6} {'─'*8} {'─'*8} {'─'*5}")
            for r in latest:
                pm = str(r['pm25']) if r['pm25'] is not None else "—"
                tp = str(r['temp_tenths']) if r['temp_tenths'] is not None else "—"
                ns = str(r['noise_db']) if r['noise_db'] is not None else "—"
                print(f"  {r['node_id']:<12} {pm:>6} {tp:>6} {ns:>6} {r['battery_mv']:>7}mV {str(r['parent'] or '—'):>8} {str(r['rank'] or '—'):>5}")

            print()
            print(f"  {CYAN}Refreshing every 3s... Press Ctrl+C to stop{NC}")

            time.sleep(3)

        except KeyboardInterrupt:
            print(f"\n  {GREEN}Monitor stopped.{NC}")
            break
        except Exception as e:
            print(f"  {RED}Error: {e}{NC}")
            time.sleep(3)

if __name__ == "__main__":
    run()
