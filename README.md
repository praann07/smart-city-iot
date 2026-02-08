# Energy-Efficient Smart City Sensor Network

**Course:** 22AIE211 — IoT Systems  
**Team:** TEAM-10  

An end-to-end IoT pipeline: 21 Contiki-NG sensor motes in a Cooja simulation send PM2.5, temperature, and noise readings over IPv6/6LoWPAN/RPL to a Python backend, which stores data in SQLite, runs a RandomForest ML model for battery-failure prediction (94.6 % accuracy), and exposes everything via a Flask REST API and a live Node-RED dashboard.

---

## Architecture

```
┌─────────────────────────────── Cooja Simulator ──────────────────────────────┐
│                                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                                  │
│   │ poll_02…08│  │ temp_09…0f│  │noise_10…16│   7 nodes each = 21 motes      │
│   │  (PM2.5)  │  │  (°C)    │  │  (dB)     │                                │
│   └─────┬─────┘  └─────┬────┘  └─────┬─────┘                                │
│         │              │              │        UDP / JSON / port 8765         │
│         └──────────────┼──────────────┘                                      │
│                        ▼                                                     │
│              ┌─────────────────┐                                             │
│              │  Border Router  │  RPL-Lite root (aaaa::1)                    │
│              └────────┬────────┘                                             │
└───────────────────────┼──────────────────────────────────────────────────────┘
                        │ tunslip6 (Serial Socket → tun0)
                        ▼
              ┌─────────────────┐
              │  collector.py   │  Listens on UDP :8765, parses JSON
              └────────┬────────┘
                       │ INSERT
                       ▼
              ┌─────────────────┐
              │   SQLite (iot.db)│  113 k+ readings, 21 nodes
              └────────┬────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   ┌────────────┐ ┌──────────┐ ┌──────────────┐
   │ Flask API  │ │ ML Model │ │  Analysis &  │
   │ (10 routes)│ │ (RF, 8f) │ │  Plots (6)   │
   │ port 5001  │ │ 94.6% acc│ │  PNG + CSV   │
   └─────┬──────┘ └──────────┘ └──────────────┘
         │
         ▼
   ┌─────────────┐
   │  Node-RED   │  Live dashboard: table, gauges,
   │  port 1880  │  bar charts, alerts, ML predictions
   └─────────────┘
```

---

## Directory Structure

| Folder | Contents |
|--------|----------|
| `contiki/nodes/` | 3 Contiki-NG C source files: pollution, temperature, noise motes |
| `backend/ingest/` | `collector.py` (UDP listener), `commands.py`, `features.py`, `powertracker_ingest.py` |
| `backend/db/` | `schema.sql`, `init_db.py`, `predictions.json`, `iot.db` |
| `dashboard/` | `flask_app_stub.py` (Flask REST API), `flows.json` (Node-RED) |
| `experiments/` | `baseline_ml.py`, `analysis_report.py`, `energy_analysis.py` |
| `experiments/results/` | 6 plots (PNG) + `node_summary.csv` |
| `experiments/artifacts/` | `failure_model.joblib` (trained RF model, 1.9 MB) |
| `scripts/` | `start_dashboard.sh`, `run_demo.sh`, `install_deps.sh`, `reseed_db.py`, etc. |
| `docs/` | `runbook.md` — full step-by-step guide |

---

## Key Features

### Embedded Layer (C / Contiki-NG)
- 3 sensor types: PM2.5 (60–120 µg/m³), temperature (18–32 °C), noise (40–90 dB)
- Probabilistic battery drain model (3000 → ~2400 mV over a 5-hour run)
- RPL-Lite routing with parent/rank reporting per packet
- JSON-over-UDP transport to border router

### Backend (Python)
- `collector.py` — live UDP listener that parses JSON and writes to SQLite
- `flask_app_stub.py` — 10 REST endpoints: `/api/metrics/latest`, `/api/alerts`, `/api/predictions`, `/api/energy`, `/api/commands/duty_cycle`, etc.
- `init_db.py` + `schema.sql` — 3 tables: `readings`, `energy_samples`, `commands`

### Machine Learning
- **Model:** RandomForest (80 trees, max_depth=10)
- **Task:** Predict battery failure from environmental sensors only (no battery info given to model)
- **Features (8):** pm25, temp_tenths, noise_db, pm25_rolling, noise_rolling, temp_rolling, congestion, node_age
- **Accuracy:** 94.6 % with stratified 80/20 split
- **Output:** Per-node risk probability + OK/FAIL label → `predictions.json`

### Dashboard (Node-RED)
- Live table of all 21 nodes (auto-refresh 5 s)
- Gauges: PM2.5, temperature, noise, battery
- HTML bar charts: per-node comparison across all metrics
- Threshold alerts (PM2.5 > 50, noise > 90)
- ML predictions panel (accuracy, per-node OK/FAIL)

### Analysis Plots
- `packets_per_node.png` — packet count per node
- `loss_rate_per_node.png` — estimated packet loss
- `timeseries_example.png` — sensor readings over time
- `battery_lifetime.png` — battery drain curves
- `energy_comparison.png` — energy usage comparison
- `duty_cycle_breakdown.png` — CPU/LPM/TX/RX breakdown

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r backend/requirements.txt

# 2. Initialize the database
python backend/db/init_db.py

# 3. (Optional) Seed with realistic synthetic data
python scripts/reseed_db.py

# 4. Train the ML model
python experiments/baseline_ml.py

# 5. Start Flask API
python dashboard/flask_app_stub.py          # → http://localhost:5001

# 6. Start Node-RED dashboard
cp dashboard/flows.json ~/.node-red/flows.json
node-red                                    # → http://localhost:1880/ui

# 7. (Live demo) Start Cooja, tunslip6, collector
# See docs/runbook.md for full instructions
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Motes | Contiki-NG 4.x, C, Cooja simulator |
| Network | IPv6, 6LoWPAN, RPL-Lite, UDP |
| Backend | Python 3.12, SQLite, Flask |
| ML | scikit-learn (RandomForest), pandas, joblib |
| Dashboard | Node-RED + node-red-dashboard |
| Analysis | matplotlib, numpy |

---

See [docs/runbook.md](docs/runbook.md) for the full step-by-step flow, Cooja setup, and data export guidance.
