"""Train a quick baseline and persist predictions for the dashboard.

Key design decisions vs. the original version:
  - `node_age` REMOVED: cumcount was trivially correlated with the
    scripted battery decay, inflating accuracy artificially.
  - `rank` ADDED: RPL rank (in 256-units) is an honest proxy for
    path length and retransmission overhead.
  - `battery_drop_rate` ADDED: rolling std of battery_mv captures
    the *rate of change*, not just the absolute position.
  - TIME-BASED SPLIT: first 80% of wall-clock data = train,
    last 20% = test.  This is the correct evaluation for time-series.
  - Feature importances are logged and persisted with predictions.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from joblib import dump
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "db" / "iot.db"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "failure_model.joblib"
PRED_PATH = Path(__file__).resolve().parents[1] / "backend" / "db" / "predictions.json"


def load_df() -> pd.DataFrame:
  conn = sqlite3.connect(DB_PATH)
  df = pd.read_sql_query("SELECT * FROM readings", conn)
  conn.close()
  return df


def make_labels(df: pd.DataFrame) -> pd.DataFrame:
  df = df.sort_values(["node_id", "recv_ts"]).copy()
  # Label: will battery drop below 2500 mV within the next 50 readings?
  df["future_low"] = (
      df.groupby("node_id")["battery_mv"].shift(-50).fillna(df["battery_mv"]) < 2500
  ).astype(int)

  # --- Sensor rolling features (no battery information given to model) ---
  for col, alias in [("pm25", "pm25_rolling"), ("noise_db", "noise_rolling"),
                     ("temp_tenths", "temp_rolling")]:
    df[alias] = (
        df.groupby("node_id")[col]
          .transform(lambda x: x.rolling(10, min_periods=1).mean())
          .fillna(0)
    )

  df["congestion"] = ((df["noise_db"] > 80) | (df["pm25"] > 100)).astype(int)

  # --- Topology feature: rank (hops into the mesh) ---
  df["rank"] = df["rank"].fillna(256).astype(int)  # 256 = 1-hop default

  # --- Battery rate-of-change (rolling std over 10 readings) ---
  # This captures how fast the battery is draining, not its absolute level.
  df["battery_drop_rate"] = (
      df.groupby("node_id")["battery_mv"]
        .transform(lambda x: x.rolling(10, min_periods=2).std())
        .fillna(0)
  )
  return df


# Honest feature set — no node_age, uses topology + rate-of-change instead.
FEAT_COLS: List[str] = [
    "pm25", "temp_tenths", "noise_db",
    "pm25_rolling", "noise_rolling", "temp_rolling",
    "congestion",
    "rank",            # RPL path length — deeper nodes drain faster
    "battery_drop_rate",  # rolling std of battery_mv — rate of change
]


def train_failure(df: pd.DataFrame) -> Tuple[RandomForestClassifier, str, Dict]:
  """
  Time-based train/test split: train on first 80% of data chronologically,
  evaluate on the last 20%.  This mirrors real deployment where the model
  is trained on historical data and predicts the near future.
  """
  feats  = df[FEAT_COLS].fillna(0)
  labels = df["future_low"]

  if labels.nunique() < 2:
    raise RuntimeError("Not enough class variety yet. Collect more data.")

  # Chronological (time-based) split — NOT random
  split_idx = int(len(df) * 0.8)
  df_sorted = df.sort_values("recv_ts")
  train_idx = df_sorted.index[:split_idx]
  test_idx  = df_sorted.index[split_idx:]

  X_train, y_train = feats.loc[train_idx], labels.loc[train_idx]
  X_test,  y_test  = feats.loc[test_idx],  labels.loc[test_idx]

  if y_train.nunique() < 2 or y_test.nunique() < 2:
    raise RuntimeError("Time split produced single-class partition. Need longer run.")

  clf = RandomForestClassifier(n_estimators=80, max_depth=10, random_state=42)
  clf.fit(X_train, y_train)
  y_pred = clf.predict(X_test)
  report = classification_report(y_test, y_pred, digits=3)

  importances: Dict = {
      col: float(imp)
      for col, imp in sorted(
          zip(FEAT_COLS, clf.feature_importances_),
          key=lambda t: t[1], reverse=True,
      )
  }
  return clf, report, importances


def latest_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
  latest_rows = df.sort_values("recv_ts").groupby("node_id").tail(1)
  feats = latest_rows[FEAT_COLS].fillna(0)
  feats.index = latest_rows["node_id"].values
  return feats


def persist_artifacts(model: RandomForestClassifier, report: str,
                      importances: Dict, df: pd.DataFrame) -> None:
  ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
  dump(model, MODEL_PATH)

  feats = latest_feature_frame(df)
  probs = model.predict_proba(feats)[:, 1]

  # Get latest raw readings (including battery_mv) for the prediction output
  latest_raw = df.sort_values("recv_ts").groupby("node_id").tail(1).set_index("node_id")

  predictions = []
  for (node_id, feat_row), prob in zip(feats.iterrows(), probs):
    predictions.append({
        "node_id": node_id,
        "risk_battery_low": float(prob),
        "pm25": float(latest_raw.loc[node_id, "pm25"]) if pd.notna(latest_raw.loc[node_id, "pm25"]) else 0.0,
        "temp_tenths": float(latest_raw.loc[node_id, "temp_tenths"]) if pd.notna(latest_raw.loc[node_id, "temp_tenths"]) else 0.0,
        "noise_db": float(latest_raw.loc[node_id, "noise_db"]) if pd.notna(latest_raw.loc[node_id, "noise_db"]) else 0.0,
        "battery_mv": float(latest_raw.loc[node_id, "battery_mv"]),
        "rank": int(latest_raw.loc[node_id, "rank"]) if pd.notna(latest_raw.loc[node_id, "rank"]) else 256,
    })

  PRED_PATH.parent.mkdir(parents=True, exist_ok=True)
  write_predictions(predictions, source="model", report=report,
                    importances=importances)


def write_predictions(preds, source: str, report: str = "",
                      importances: Dict = None) -> None:
  PRED_PATH.parent.mkdir(parents=True, exist_ok=True)
  payload = {
      "generated_ts": int(time.time()),
      "source": source,
      "report": report,
      "feature_importances": importances or {},
      "predictions": preds,
  }
  with PRED_PATH.open("w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)


def heuristic_predictions(df: pd.DataFrame) -> None:
  latest_rows = df.sort_values("recv_ts").groupby("node_id").tail(1)
  preds = []
  safe = lambda v, default=0.0: float(v) if pd.notna(v) else float(default)
  for _, row in latest_rows.iterrows():
    battery_mv = safe(row.get("battery_mv"), 3000.0)
    pm25 = safe(row.get("pm25"), 0.0)
    noise_db = safe(row.get("noise_db"), 0.0)
    rank = int(row.get("rank") or 256)
    risk = 0.0
    if battery_mv < 2800:
      risk = 0.9
    elif battery_mv < 2900:
      risk = 0.4
    elif rank >= 512:       # 2-hop+ nodes are higher risk regardless
      risk = max(risk, 0.3)
    preds.append({
        "node_id": row["node_id"],
        "risk_battery_low": float(risk),
        "pm25": pm25,
        "temp_tenths": safe(row.get("temp_tenths"), 0.0),
        "noise_db": noise_db,
        "battery_mv": battery_mv,
        "rank": rank,
    })
  write_predictions(preds, source="heuristic",
                    report="fallback due to single-class or insufficient data")


def main():
  df = load_df()
  if df.empty:
    print("No data yet. Run Cooja + collector first.")
    return
  df = make_labels(df)
  try:
    model, report, importances = train_failure(df)
  except RuntimeError as exc:
    print(str(exc))
    heuristic_predictions(df)
    print("Wrote heuristic predictions to", PRED_PATH)
    return
  persist_artifacts(model, report, importances, df)
  print("Saved model to", MODEL_PATH)
  print("Saved predictions to", PRED_PATH)
  print("\n--- Classification Report (time-based split) ---")
  print(report)
  print("\n--- Feature Importances (higher = more influential) ---")
  for feat, imp in sorted(importances.items(), key=lambda t: t[1], reverse=True):
    bar = '#' * int(imp * 50)
    print(f"  {feat:<22} {imp:.4f}  {bar}")


if __name__ == "__main__":
  main()
