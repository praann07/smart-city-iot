# Dashboard

Two components work together:

## 1. Flask REST API (`flask_app_stub.py`)

Run with `python dashboard/flask_app_stub.py` → serves on **port 5001**.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/latest` | GET | Latest reading per node (21 rows) |
| `/api/metrics/history?node_id=...` | GET | Recent readings for one node |
| `/api/metrics/summary` | GET | Aggregated stats per node |
| `/api/metrics/series?limit=200` | GET | Time-series data (all or per node) |
| `/api/alerts?pm25=50&noise=90` | GET | Nodes exceeding thresholds |
| `/api/predictions` | GET | ML predictions (cached) with fallback heuristic |
| `/api/energy` | GET/POST | Energy samples (GET latest, POST new) |
| `/api/energy/summary` | GET | Energy aggregation per node |
| `/api/commands/duty_cycle` | GET/POST | Adaptive duty-cycle commands |
| `/api/features/derived` | GET | Computed features (loss rate, battery drop/s) |
| `/health` | GET | Health check |

## 2. Node-RED Dashboard (`flows.json`)

Copy to Node-RED and start:
```bash
cp dashboard/flows.json ~/.node-red/flows.json
node-red    # → http://localhost:1880/ui
```

Dashboard sections:
- **Live Table** — all 21 nodes with latest sensor readings (auto-refresh 5 s)
- **Gauges** — PM2.5, Temperature, Noise, Battery voltage
- **Bar Charts** — per-node comparison across all metrics
- **Alerts** — threshold-based warnings (PM2.5 > 50, noise > 90)
- **ML Predictions** — model accuracy + per-node OK/FAIL status

Requires: `node-red-dashboard` package (`cd ~/.node-red && npm install node-red-dashboard`).
