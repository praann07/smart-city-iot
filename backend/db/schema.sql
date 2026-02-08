PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  pm25 INTEGER,
  temp_tenths INTEGER,
  noise_db INTEGER,
  battery_mv INTEGER,
  seq INTEGER,
  node_ts INTEGER,
  recv_ts INTEGER NOT NULL,
  parent TEXT,
  rank INTEGER
);

CREATE INDEX IF NOT EXISTS idx_readings_node_ts ON readings(node_id, node_ts);
CREATE INDEX IF NOT EXISTS idx_readings_recv_ts ON readings(recv_ts);

CREATE TABLE IF NOT EXISTS energy_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  cpu_ms REAL,
  lpm_ms REAL,
  tx_ms REAL,
  rx_ms REAL,
  battery_mv INTEGER,
  node_ts INTEGER,
  recv_ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_energy_node_ts ON energy_samples(node_id, node_ts);

CREATE TABLE IF NOT EXISTS commands (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  duty_cycle INTEGER,
  issued_ts INTEGER NOT NULL,
  status TEXT DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_commands_node ON commands(node_id);
