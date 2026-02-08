# Reliable data export from Cooja (keep Cooja open)

Goal: stream packets and energy metrics out of Cooja without it closing or dropping data.

## Do not close Cooja
- Run the simulator in the GUI and keep the window open; you can minimize it. Only `File → Quit` or closing the window stops the simulation. Opening terminals or running Python scripts will not close it.
- Disable OS sleep/lock during long runs.

## Packet path (recommended: UDP over SLIP to host)
1. Use the 6LoWPAN border router mote (tun-slip). Set target host IPv6 to your host (often `aaaa::1` in examples).
2. On your host, start the backend first: `python backend/ingest/collector.py --port 8765`.
3. In Cooja, for the border router serial port, enable `Tools → Serial Socket (random TCP port)` or `Tools → Serial 2 pty`. This mirrors the serial to a pseudo-TTY.
4. Start the SLIP router on your host in a separate terminal, pointing to that TTY. Example (Contiki-NG default): `sudo ./tunslip6 -v2 -a 127.0.0.1 -p <PORT> aaaa::1/64`.
5. The motes send UDP to `aaaa::1` port 8765. The collector captures and writes to SQLite.

## Logging to file as backup
- In Cooja: `Simulation → Log Listener → Save` to a file. This keeps the GUI running and does not pause the sim. Use it as a secondary source in case packets drop.
- Add PowerTracker and Energy plugin; after the run, export CSV. This does not close Cooja.

## Avoid packet loss
- Start the collector before pressing "Start" in Cooja so the UDP port is bound.
- Use WAL in SQLite (already enabled) to handle bursts.
- If you expect >1k queued packets, raise `QUEUE_MAX` in `collector.py`.
- Optionally run a local MQTT broker (Mosquitto) and forward from border router to MQTT if you prefer publish/subscribe buffering.
- Powertrace is enabled in node code; you can also export Energy plugin CSV for plots.

## Re-running without closing the GUI
- Pause simulation, clear `Log Listener` if needed, restart backend, then resume simulation. No need to close Cooja. Powertrace messages remain in logs; Energy plugin CSV is per-node.
