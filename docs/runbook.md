# Runbook

## Environment
- Use Contiki-NG (stable release) + Cooja built from the same tag.
- Python 3.10+, recommended venv; SQLite for quick persistence.
- Keep Cooja open: run simulations inside the GUI; run backend scripts from an external terminal. Do **not** quit Cooja when opening terminals; Cooja only closes if you explicitly exit the GUI.

## High-level steps (run order)
1) Init DB: `python backend/db/init_db.py`
2) Start collector: `python backend/ingest/collector.py --port 8765`
3) Start SLIP for BR: `./scripts/start_tunslip6.sh <tty_port> aaaa::1/64`
4) Build Cooja sim: 20 motes (pollution/temp/noise) + border router; enable PowerTracker + Energy plugin; radio UDGM.
5) Start simulation (keep GUI open); packets flow via UDP to collector → SQLite (`backend/db/iot.db`).
6) Compute features: `python backend/ingest/features.py`.
7) Train quick ML: `python experiments/baseline_ml.py` after data exists.
8) Dashboard/API: `python dashboard/flask_app_stub.py` or import `dashboard/flows.json` into Node-RED.
9) Feedback: `python backend/ingest/commands.py aaaa::1 poll_03 20` (example duty-cycle update).

## Cooja data export reliability
- Configure the border router to forward logs/UDP packets to your host IP; prefer IPv4 UDP for simplicity.
- Use `collect-view` or `serial2pty` in Cooja to mirror serial output to a pseudo-TTY; the backend can read that file descriptor if needed.
- Enable Cooja log output to a file (Simulation → Log Listener → Save) **and** keep the GUI open. Saving logs does not stop the simulation.
- Avoid closing the Cooja window; you can minimize it. Running terminals will not close Cooja.
- For long runs, disable GUI auto-sleep/screensaver to avoid focus-related pauses.

## Packet loss prevention during collection
- Start backend listener before unpausing Cooja; it binds to the UDP port and buffers packets.
- Use a small in-memory queue with disk-backed WAL (SQLite) to avoid drops if the app hiccups.
- If using MQTT, run a local broker (e.g., Eclipse Mosquitto) and point the border router to it; MQTT handles reconnect buffering.

## Energy tracking
- In Cooja: Tools → Radio Logger, PowerTracker, and the Energy plugin. Export CSV after the run.
- In Contiki nodes, include `powertrace` for per-node energy sampling; send summaries every N packets if desired.

## Reproducibility
- Fix seeds in Cooja (Simulation → Random Seed) and document radio model parameters (UDGM or MRM, Tx/Rx success, interference range).

## Safety with terminals and Cooja
- Run `python ...` in your OS terminal; Cooja stays running. Only `File → Quit` or closing the window stops it.
- If you need to restart the backend, pause Cooja first, restart the backend, then resume.
