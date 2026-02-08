"""Train a quick baseline and persist predictions for the dashboard."""

import json
import sqlite3
import time
from pathlib import Path
from typing import Tuple

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from joblib import dump

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
  # Derived features from sensor readings (NOT battery)
  grp_pm = df.groupby("node_id")["pm25"]
  df["pm25_rolling"] = grp_pm.transform(lambda x: x.rolling(10, min_periods=1).mean()).fillna(0)
  grp_noise = df.groupby("node_id")["noise_db"]
  df["noise_rolling"] = grp_noise.transform(lambda x: x.rolling(10, min_periods=1).mean()).fillna(0)
  grp_temp = df.groupby("node_id")["temp_tenths"]
  df["temp_rolling"] = grp_temp.transform(lambda x: x.rolling(10, min_periods=1).mean()).fillna(0)
  df["congestion"] = ((df["noise_db"] > 80) | (df["pm25"] > 100)).astype(int)
  # Sequence number as proxy for node age / uptime
  df["node_age"] = df.groupby("node_id").cumcount()
  return df


def train_failure(df: pd.DataFrame) -> Tuple[RandomForestClassifier, str]:
  # Predict battery failure purely from environmental sensor readings.
  # This is the hard (and interesting) problem: can sensor load patterns
  # predict which nodes will fail?  No battery info is given to the model.
  feat_cols = ["pm25", "temp_tenths", "noise_db",
               "pm25_rolling", "noise_rolling", "temp_rolling",
               "congestion", "node_age"]
  feats = df[feat_cols].fillna(0)
  labels = df["future_low"]
  if labels.nunique() < 2:
    raise RuntimeError("Not enough class variety yet. Collect more data.")
  X_train, X_test, y_train, y_test = train_test_split(feats, labels, test_size=0.2, stratify=labels)
  clf = RandomForestClassifier(n_estimators=80, max_depth=10, random_state=42)
  clf.fit(X_train, y_train)
  y_pred = clf.predict(X_test)
  report = classification_report(y_test, y_pred, digits=3)
  return clf, report


def latest_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
  feat_cols = ["pm25", "temp_tenths", "noise_db",
               "pm25_rolling", "noise_rolling", "temp_rolling",
               "congestion", "node_age"]
  latest_rows = df.sort_values("recv_ts").groupby("node_id").tail(1)
  feats = latest_rows[feat_cols].fillna(0)
  feats.index = latest_rows["node_id"].values
  return feats


def persist_artifacts(model: RandomForestClassifier, report: str, df: pd.DataFrame) -> None:
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
    })

  PRED_PATH.parent.mkdir(parents=True, exist_ok=True)
  write_predictions(predictions, source="model", report=report)


def write_predictions(preds, source: str, report: str = "") -> None:
  PRED_PATH.parent.mkdir(parents=True, exist_ok=True)
  payload = {
      "generated_ts": int(time.time()),
      "source": source,
      "report": report,
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
    risk = 0.0
    if battery_mv < 2800:
      risk = 0.9
    elif battery_mv < 2900:
      risk = 0.4
    preds.append({
        "node_id": row["node_id"],
        "risk_battery_low": float(risk),
        "pm25": pm25,
        "temp_tenths": safe(row.get("temp_tenths"), 0.0),
        "noise_db": noise_db,
        "battery_mv": battery_mv,
    })
  write_predictions(preds, source="heuristic", report="fallback due to single-class data")


def main():
  df = load_df()
  if df.empty:
    print("No data yet. Run Cooja + collector first.")
    return
  df = make_labels(df)
  try:
    model, report = train_failure(df)
  except RuntimeError as exc:
    print(str(exc))
    heuristic_predictions(df)
    print("Wrote heuristic predictions to", PRED_PATH)
    return
  persist_artifacts(model, report, df)
  print("Saved model to", MODEL_PATH)
  print("Saved predictions to", PRED_PATH)
  print(report)


if __name__ == "__main__":
  main()
