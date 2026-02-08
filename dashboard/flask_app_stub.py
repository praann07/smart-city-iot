from flask import Flask, jsonify, request
import json
import sqlite3
from pathlib import Path
import time

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "db" / "iot.db"
PRED_CACHE_PATH = Path(__file__).resolve().parents[1] / "backend" / "db" / "predictions.json"

app = Flask(__name__)


def query_db(query, args=()):
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  cur = conn.execute(query, args)
  rows = [dict(r) for r in cur.fetchall()]
  conn.close()
  return rows


def load_prediction_cache():
  try:
    with PRED_CACHE_PATH.open("r", encoding="utf-8") as f:
      data = json.load(f)
    preds = data.get("predictions") or []
    if preds:
      return {
          "source": "cached_model",
          "generated_ts": data.get("generated_ts"),
          "report": data.get("report"),
          "predictions": preds,
      }
  except FileNotFoundError:
    return None
  except Exception:
    return None
  return None


@app.route("/api/metrics/latest")
def latest():
  rows = query_db(
      """
      SELECT r.* FROM readings r
      JOIN (
        SELECT node_id, MAX(recv_ts) AS mx FROM readings GROUP BY node_id
      ) t ON r.node_id = t.node_id AND r.recv_ts = t.mx
      ORDER BY r.node_id;
      """
  )
  return jsonify(rows)


@app.route("/api/metrics/history")
def history():
  node_id = request.args.get("node_id")
  limit = int(request.args.get("limit", "100"))
  if not node_id:
    return jsonify({"error": "node_id required"}), 400
  rows = query_db(
      "SELECT * FROM readings WHERE node_id=? ORDER BY recv_ts DESC LIMIT ?;",
      (node_id, limit),
  )
  return jsonify(rows)


@app.route("/api/metrics/summary")
def summary():
  rows = query_db(
      """
      SELECT node_id,
             COUNT(*) AS count,
             MAX(recv_ts) AS latest_recv_ts,
             AVG(pm25) AS avg_pm25,
             AVG(temp_tenths) AS avg_temp_tenths,
             AVG(noise_db) AS avg_noise_db
      FROM readings
      GROUP BY node_id
      ORDER BY node_id;
      """
  )
  return jsonify(rows)


@app.route("/api/metrics/series")
def series():
  node_id = request.args.get("node_id")
  limit = int(request.args.get("limit", "200"))
  if node_id:
    rows = query_db(
        "SELECT * FROM readings WHERE node_id=? ORDER BY recv_ts DESC LIMIT ?;",
        (node_id, limit),
    )
  else:
    rows = query_db(
        "SELECT * FROM readings ORDER BY recv_ts DESC LIMIT ?;",
        (limit,),
    )
  return jsonify(rows)


@app.route("/api/alerts")
def alerts():
  pm25_thresh = float(request.args.get("pm25", "50"))
  noise_thresh = float(request.args.get("noise", "90"))
  rows = query_db(
      """
      WITH latest AS (
        SELECT r.*
        FROM readings r
        JOIN (
          SELECT node_id, MAX(recv_ts) AS mx FROM readings GROUP BY node_id
        ) t ON r.node_id = t.node_id AND r.recv_ts = t.mx
      )
      SELECT *
      FROM latest
      WHERE (pm25 IS NOT NULL AND pm25 > ?)
         OR (noise_db IS NOT NULL AND noise_db > ?)
      ORDER BY recv_ts DESC;
      """,
      (pm25_thresh, noise_thresh),
  )
  return jsonify(rows)


@app.route("/api/predictions")
def predictions():
  cached = load_prediction_cache()
  if cached:
    return jsonify(cached)

  # Fallback heuristic if no cached model output is available
  pm25_thresh = float(request.args.get("pm25", "50"))
  noise_thresh = float(request.args.get("noise", "90"))
  batt_thresh = float(request.args.get("battery", "20"))
  rows = query_db(
      """
      WITH latest AS (
        SELECT r.*
        FROM readings r
        JOIN (
          SELECT node_id, MAX(recv_ts) AS mx FROM readings GROUP BY node_id
        ) t ON r.node_id = t.node_id AND r.recv_ts = t.mx
      )
      SELECT node_id, pm25, temp_tenths, noise_db, battery_mv, parent, rank, recv_ts
      FROM latest
      ORDER BY node_id;
      """
  )
  preds = []
  for r in rows:
    risks = []
    if r.get("battery_mv") is not None and r["battery_mv"] < batt_thresh:
      risks.append("battery_low")
    if r.get("pm25") is not None and r["pm25"] > pm25_thresh:
      risks.append("pollution_high")
    if r.get("noise_db") is not None and r["noise_db"] > noise_thresh:
      risks.append("noise_high")
    preds.append({
        "node_id": r.get("node_id"),
        "recv_ts": r.get("recv_ts"),
        "risks": risks,
        "risk_score": len(risks),
    })
  return jsonify({"source": "heuristic", "predictions": preds})


@app.route("/api/energy", methods=["POST", "GET"])
def energy():
  if request.method == "POST":
    payload = request.get_json(force=True, silent=True) or []
    if isinstance(payload, dict):
      payload = [payload]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for row in payload:
      cur.execute(
          """
          INSERT INTO energy_samples(node_id, cpu_ms, lpm_ms, tx_ms, rx_ms, battery_mv, node_ts, recv_ts)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
              row.get("node_id"),
              row.get("cpu_ms"),
              row.get("lpm_ms"),
              row.get("tx_ms"),
              row.get("rx_ms"),
              row.get("battery_mv"),
              row.get("node_ts"),
              int(time.time()),
          ),
      )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "inserted": len(payload)}), 201
  # GET latest per node
  rows = query_db(
      """
      SELECT e.* FROM energy_samples e
      JOIN (
        SELECT node_id, MAX(recv_ts) AS mx FROM energy_samples GROUP BY node_id
      ) t ON e.node_id = t.node_id AND e.recv_ts = t.mx
      ORDER BY e.node_id;
      """
  )
  return jsonify(rows)


@app.route("/api/energy/summary")
def energy_summary():
  rows = query_db(
      """
      SELECT node_id,
             COUNT(*) AS samples,
             AVG(cpu_ms) AS avg_cpu_ms,
             AVG(lpm_ms) AS avg_lpm_ms,
             AVG(tx_ms) AS avg_tx_ms,
             AVG(rx_ms) AS avg_rx_ms,
             MAX(battery_mv) AS max_battery_mv,
             MIN(battery_mv) AS min_battery_mv,
             MAX(recv_ts) AS latest_recv_ts
      FROM energy_samples
      GROUP BY node_id
      ORDER BY node_id;
      """
  )
  return jsonify(rows)


@app.route("/api/commands/duty_cycle", methods=["POST", "GET"])
def duty_cycle():
  if request.method == "POST":
    data = request.get_json(force=True, silent=True) or {}
    node_id = data.get("node_id") or "all"
    duty = data.get("duty_cycle")
    if duty is None:
      return jsonify({"error": "duty_cycle required"}), 400
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO commands(node_id, duty_cycle, issued_ts, status)
        VALUES (?, ?, ?, 'queued')
        """,
        (node_id, int(duty), int(time.time())),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "queued", "node_id": node_id, "duty_cycle": int(duty)}), 201
  # GET queued commands
  rows = query_db(
      "SELECT * FROM commands ORDER BY issued_ts DESC LIMIT 100;"
  )
  return jsonify(rows)


@app.route("/api/features")
def features():
  # simple windowed aggregation example
  window = int(request.args.get("window", "300"))
  rows = query_db(
      """
      SELECT node_id, (recv_ts / ?) * ? AS win,
             COUNT(*) AS cnt,
             AVG(pm25) AS avg_pm25,
             AVG(temp_tenths) AS avg_temp_tenths,
             AVG(noise_db) AS avg_noise_db,
             (MAX(battery_mv) - MIN(battery_mv)) * 1.0 / MAX(COUNT(*), 1) AS drop_per_pkt
      FROM readings
      GROUP BY node_id, win
      ORDER BY node_id, win DESC
      LIMIT 200;
      """,
      (window, window),
  )
  return jsonify(rows)


@app.route("/api/features/derived")
def features_derived():
  """Compute derived features per node from readings (loss, battery drop, parent switches)."""
  window = int(request.args.get("window", "900"))  # seconds
  rows = query_db(
      """
      WITH latest AS (
        SELECT r.*
        FROM readings r
        JOIN (
          SELECT node_id, MAX(recv_ts) AS mx FROM readings GROUP BY node_id
        ) t ON r.node_id = t.node_id AND r.recv_ts = t.mx
      ),
      spans AS (
        SELECT node_id,
               MIN(recv_ts) AS min_recv,
               MAX(recv_ts) AS max_recv,
               MIN(seq) AS min_seq,
               MAX(seq) AS max_seq,
               COUNT(*) AS cnt,
               COUNT(DISTINCT parent) AS parent_changes,
               MIN(battery_mv) AS min_batt,
               MAX(battery_mv) AS max_batt
        FROM readings
        WHERE recv_ts >= (SELECT MAX(recv_ts) FROM readings) - ?
        GROUP BY node_id
      )
      SELECT l.node_id,
             l.pm25,
             l.temp_tenths,
             l.noise_db,
             l.battery_mv,
             l.parent,
             l.rank,
             s.cnt,
             (s.max_seq - s.min_seq + 1) AS expected_pkts,
             (s.max_seq - s.min_seq + 1 - s.cnt) AS est_loss,
             s.parent_changes AS parent_switches,
             CASE WHEN (s.max_recv - s.min_recv) > 0 THEN (s.max_batt - s.min_batt) * 1.0 / (s.max_recv - s.min_recv) ELSE 0 END AS battery_drop_per_s
      FROM latest l
      LEFT JOIN spans s ON l.node_id = s.node_id
      ORDER BY l.node_id;
      """,
      (window,),
  )
  return jsonify(rows)


@app.route("/health")
def health():
  return jsonify({"status": "ok"})


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5001, debug=True)
