import argparse
import asyncio
import json
import logging
import signal
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "iot.db"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
DEFAULT_UDP_PORT = 8765
QUEUE_MAX = 1000
BATCH_SIZE = 50

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
LOGGER = logging.getLogger("collector")


def ensure_db(conn: sqlite3.Connection) -> None:
  with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    conn.executescript(f.read())
  conn.execute("PRAGMA journal_mode=WAL;")
  conn.execute("PRAGMA synchronous=NORMAL;")


def open_db() -> sqlite3.Connection:
  conn = sqlite3.connect(DB_PATH, check_same_thread=False)
  ensure_db(conn)
  return conn


def normalize_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
  return {
      "node_id": str(raw.get("node_id", "unknown")),
      "pm25": raw.get("pm25"),
      "temp_tenths": raw.get("temp_tenths"),
      "noise_db": raw.get("noise_db"),
      "battery_mv": raw.get("battery_mv"),
      "seq": raw.get("seq"),
      "node_ts": raw.get("timestamp"),
      "parent": raw.get("parent"),
      "rank": raw.get("rank"),
  }


class DBWriter:
  def __init__(self, conn: sqlite3.Connection):
    self.conn = conn

  def insert_batch(self, batch: list[Dict[str, Any]]) -> None:
    if not batch:
      return
    cursor = self.conn.cursor()
    cursor.executemany(
        """
        INSERT INTO readings(node_id, pm25, temp_tenths, noise_db, battery_mv, seq, node_ts, recv_ts, parent, rank)
        VALUES (:node_id, :pm25, :temp_tenths, :noise_db, :battery_mv, :seq, :node_ts, :recv_ts, :parent, :rank)
        """,
        batch,
    )
    self.conn.commit()


class UdpCollector(asyncio.DatagramProtocol):
  def __init__(self, queue: "asyncio.Queue[Dict[str, Any]]"):
    self.queue = queue

  def datagram_received(self, data: bytes, addr):  # type: ignore[override]
    try:
      # Some motes terminate JSON with a trailing NUL; strip it (and any padding) before parsing.
      clean = data.split(b"\x00", 1)[0].strip()
      if not clean:
        return
      parsed = json.loads(clean.decode("utf-8"))
      payload = normalize_payload(parsed)
      payload["recv_ts"] = int(asyncio.get_event_loop().time())
      try:
        self.queue.put_nowait(payload)
      except asyncio.QueueFull:
        LOGGER.warning("Queue full; dropping packet from %s", addr)
    except Exception as exc:  # broad to keep collector alive
      LOGGER.warning("Decode error from %s: %s", addr, exc)


async def writer_loop(queue: "asyncio.Queue[Dict[str, Any]]", dbw: DBWriter, flush_interval: float = 2.0):
  batch: list[Dict[str, Any]] = []
  while True:
    try:
      item = await asyncio.wait_for(queue.get(), timeout=flush_interval)
      batch.append(item)
      queue.task_done()
      if len(batch) >= BATCH_SIZE:
        dbw.insert_batch(batch)
        batch.clear()
    except asyncio.TimeoutError:
      if batch:
        dbw.insert_batch(batch)
        batch.clear()


def install_signals(loop: asyncio.AbstractEventLoop):
  for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, loop.stop)


async def main(port: int) -> None:
  queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX)
  conn = open_db()
  dbw = DBWriter(conn)

  loop = asyncio.get_running_loop()
  install_signals(loop)

  transport, _ = await loop.create_datagram_endpoint(
      lambda: UdpCollector(queue), local_addr=("::", port))
  LOGGER.info("UDP collector listening on port %d", port)

  writer_task = asyncio.create_task(writer_loop(queue, dbw))

  try:
    await asyncio.Future()  # run until stopped
  finally:
    transport.close()
    writer_task.cancel()
    await asyncio.gather(writer_task, return_exceptions=True)
    conn.close()
    LOGGER.info("Collector stopped cleanly")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="UDP collector for Contiki packets")
  parser.add_argument("--port", type=int, default=DEFAULT_UDP_PORT, help="UDP port to bind")
  args = parser.parse_args()
  asyncio.run(main(args.port))
