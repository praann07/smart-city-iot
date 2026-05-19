"""
mock_cooja.py — Python stand-in for the Cooja simulation.

Simulates 21 motes exactly as the C firmware would behave:
  - 7 pollution nodes  (rank 256 = 1-hop,  rank 512 = 2-hop)
  - 7 temperature nodes
  - 7 noise nodes
  - per-node RPL rank varies → different battery drain rates
  - sends JSON-over-UDP to localhost:8765 (collector)
  - listens on UDP port 8766 for downlink duty_cycle commands
  - logs any received command to prove the downlink path works

Usage:
    python3 scripts/mock_cooja.py [--duration 30] [--collector-port 8765]
"""

import argparse
import asyncio
import json
import logging
import math
import random
import time

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
)

COLLECTOR_HOST = "127.0.0.1"
COLLECTOR_PORT = 8765
CMD_PORT       = 8766        # downlink: collector → mote

# ── Topology: assign RPL rank to each node ──────────────────────────────────
# rank 256  = 1 hop  (directly peers with border router)
# rank 512  = 2 hops (relayed via a 1-hop node)
# rank 768  = 3 hops (relayed twice) — deep nodes, will drain fastest
NODE_CONFIG = {
    # node_id       : (type,       rank)
    "poll_02": ("pollution",   256),
    "poll_03": ("pollution",   256),
    "poll_04": ("pollution",   512),
    "poll_05": ("pollution",   512),
    "poll_06": ("pollution",   256),
    "poll_07": ("pollution",   768),  # deep node — fast drain
    "poll_08": ("pollution",   512),
    "temp_09": ("temperature", 256),
    "temp_0a": ("temperature", 256),
    "temp_0b": ("temperature", 512),
    "temp_0c": ("temperature", 768),  # deep node — fast drain
    "temp_0d": ("temperature", 256),
    "temp_0e": ("temperature", 512),
    "temp_0f": ("temperature", 256),
    "noise_10": ("noise",      256),
    "noise_11": ("noise",      256),
    "noise_12": ("noise",      512),
    "noise_13": ("noise",      256),
    "noise_14": ("noise",      768),  # deep node — fast drain
    "noise_15": ("noise",      512),
    "noise_16": ("noise",      768),  # deep node — fast drain
}

# Parent mapping (mirrors RPL tree implied by ranks above)
PARENT_OF = {
    "poll_04": "0003", "poll_05": "0002", "poll_07": "0004",
    "poll_08": "0005",
    "temp_0b": "0009", "temp_0c": "000b", "temp_0e": "000a",
    "noise_12": "0010", "noise_14": "0012",
    "noise_15": "0011", "noise_16": "0015",
}


def get_parent(node_id: str, rank: int) -> str:
    if rank == 256:
        return "0001"   # direct child of border router
    return PARENT_OF.get(node_id, "0001")


# ── Sensor models (mirrors C firmware diurnal logic) ─────────────────────────

SIM_START = time.time()


def virtual_hour() -> int:
    elapsed_h = (time.time() - SIM_START) / 3600.0
    # 1 real second = 60 sim-seconds (fast simulation)
    fast_h = elapsed_h * 60
    return int((6 + fast_h)) % 24


def sample_pm25() -> int:
    vh = virtual_hour()
    if (7 <= vh < 9) or (17 <= vh < 19):
        base = 95
    elif vh >= 22 or vh < 5:
        base = 35
    else:
        base = 62
    return max(0, base + random.randint(-12, 12))


def sample_temp_tenths() -> int:
    vh = virtual_hour()
    if vh < 14:
        base = 180 + max(0, vh - 6) * 10
    else:
        base = 260 - (vh - 14) * 10
    base = max(180, min(260, base))
    return base + random.randint(-10, 10)


def sample_noise_db() -> int:
    vh = virtual_hour()
    if (7 <= vh < 9) or (17 <= vh < 19):
        base = 78
    elif vh >= 22 or vh < 5:
        base = 43
    else:
        base = 58
    return max(30, min(100, base + random.randint(-10, 10)))


def drain_battery(battery_mv: float, rank: int) -> float:
    hop = rank // 256
    r = random.random()
    if r < 0.25:
        drain = 0
    elif r < 0.75:
        drain = 1 + hop
    else:
        drain = 2 + hop * 2
    return max(0.0, battery_mv - drain)


def fake_energest(uptime_s: float) -> dict:
    """Generate realistic-looking cumulative energest counters."""
    total_ms = int(uptime_s * 1000)
    lpm_frac = 0.93
    tx_frac  = 0.003
    rx_frac  = 0.004
    cpu_frac = 1.0 - lpm_frac - tx_frac - rx_frac
    return {
        "cpu_ms": int(total_ms * cpu_frac),
        "lpm_ms": int(total_ms * lpm_frac),
        "tx_ms":  int(total_ms * tx_frac),
        "rx_ms":  int(total_ms * rx_frac),
    }


# ── Mote coroutine ────────────────────────────────────────────────────────────

class MockMote:
    def __init__(self, node_id: str, mote_type: str, rank: int,
                 transport: asyncio.DatagramTransport,
                 cmd_recv_log: list):
        self.node_id      = node_id
        self.mote_type    = mote_type
        self.rank         = rank
        self.battery_mv   = 3000.0
        self.seqno        = 0
        self.send_interval = 10.0 if mote_type != "temperature" else 15.0
        self.transport    = transport
        self.cmd_recv_log = cmd_recv_log
        self.log          = logging.getLogger(node_id)
        self.start_time   = time.time()

    def build_packet(self) -> bytes:
        uptime = time.time() - self.start_time
        energy = fake_energest(uptime)
        parent = get_parent(self.node_id, self.rank)

        pkt: dict = {
            "node_id":    self.node_id,
            "battery_mv": int(self.battery_mv),
            "seq":        self.seqno,
            "timestamp":  int(uptime),
            "parent":     parent,
            "rank":       self.rank,
            **energy,
        }
        if self.mote_type == "pollution":
            pkt["pm25"] = sample_pm25()
        elif self.mote_type == "temperature":
            pkt["temp_tenths"] = sample_temp_tenths()
        else:
            pkt["noise_db"] = sample_noise_db()

        return (json.dumps(pkt) + "\x00").encode()

    async def run(self, duration: float):
        end = time.time() + duration
        while time.time() < end:
            self.battery_mv = drain_battery(self.battery_mv, self.rank)
            pkt = self.build_packet()
            try:
                self.transport.sendto(pkt, (COLLECTOR_HOST, COLLECTOR_PORT))
                self.log.info(
                    "TX seq=%d batt=%d mV rank=%d",
                    self.seqno, int(self.battery_mv), self.rank
                )
            except Exception as e:
                self.log.error("Send failed: %s", e)
            self.seqno += 1
            await asyncio.sleep(self.send_interval)


# ── Downlink command listener ─────────────────────────────────────────────────

class CmdListener(asyncio.DatagramProtocol):
    """Listens on CMD_PORT for duty_cycle commands — proves downlink path."""
    def __init__(self, recv_log: list):
        self.recv_log = recv_log
        self.log = logging.getLogger("CMD_LISTENER")

    def datagram_received(self, data: bytes, addr):
        try:
            clean = data.split(b"\x00", 1)[0].strip()
            msg = json.loads(clean.decode())
            self.recv_log.append({"from": addr, "msg": msg, "ts": time.time()})
            self.log.info(
                "DOWNLINK RECEIVED from %s: %s  ← command delivery WORKS", addr, msg
            )
        except Exception as e:
            self.log.warning("Bad command packet: %s", e)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_simulation(duration: float, collector_port: int):
    global COLLECTOR_PORT
    COLLECTOR_PORT = collector_port

    loop = asyncio.get_running_loop()
    cmd_recv_log: list = []
    run_start_ts = int(time.time())

    # Open one shared UDP socket for all mote → collector traffic
    tx_transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol,
        local_addr=("0.0.0.0", 0),
        family=2,  # AF_INET
    )

    # Open downlink listener on CMD_PORT
    cmd_transport, _ = await loop.create_datagram_endpoint(
        lambda: CmdListener(cmd_recv_log),
        local_addr=("0.0.0.0", CMD_PORT),
    )
    logging.getLogger("SETUP").info(
        "Downlink listener UP on port %d", CMD_PORT
    )

    motes = []
    for i, (node_id, (mtype, rank)) in enumerate(NODE_CONFIG.items()):
        mote = MockMote(node_id, mtype, rank, tx_transport, cmd_recv_log)
        motes.append(mote)

    tasks = []
    for i, mote in enumerate(motes):
        delay = i * 0.15
        async def _run(m=mote, d=delay):
            await asyncio.sleep(d)
            await m.run(duration)
        tasks.append(asyncio.create_task(_run()))

    # ── Downlink test: after 5 s, send a duty_cycle command to poll_03 ──
    async def _send_downlink_command():
        await asyncio.sleep(5)
        cmd = json.dumps({"node_id": "poll_03", "duty_cycle": 20}).encode() + b"\x00"
        sock_transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            local_addr=("0.0.0.0", 0),
            family=2,
        )
        sock_transport.sendto(cmd, ("127.0.0.1", CMD_PORT))
        sock_transport.close()
        logging.getLogger("DOWNLINK_TEST").info(
            "Sent duty_cycle=20 command to port %d → waiting for echo...", CMD_PORT
        )
    tasks.append(asyncio.create_task(_send_downlink_command()))

    logging.getLogger("SETUP").info(
        "Simulating %d motes for %.0f seconds → sending to %s:%d",
        len(motes), duration, COLLECTOR_HOST, COLLECTOR_PORT,
    )

    await asyncio.gather(*tasks)

    tx_transport.close()
    cmd_transport.close()
    return cmd_recv_log, run_start_ts


def print_summary(cmd_recv_log: list, duration: float, run_start_ts: int):
    import sqlite3, pathlib
    DB = pathlib.Path(__file__).resolve().parents[1] / "backend" / "db" / "iot.db"
    conn = sqlite3.connect(DB)

    rows_after = conn.execute(
        "SELECT COUNT(*) FROM readings WHERE recv_ts >= ?", (run_start_ts,)
    ).fetchone()[0]
    energy_after = conn.execute(
        "SELECT COUNT(*) FROM energy_samples WHERE recv_ts >= ?", (run_start_ts,)
    ).fetchone()[0]
    nodes_seen = conn.execute(
        "SELECT COUNT(DISTINCT node_id) FROM readings WHERE recv_ts >= ?",
        (run_start_ts,)
    ).fetchone()[0]

    # Packet-loss via seq gaps — only this run's data
    loss_data = conn.execute(
        """
        SELECT node_id,
               COUNT(*)          AS pkts,
               MAX(seq)-MIN(seq)+1 AS expected,
               MAX(battery_mv)   AS batt_start,
               MIN(battery_mv)   AS batt_end
        FROM readings
        WHERE recv_ts >= ?
        GROUP BY node_id
        ORDER BY node_id
        """,
        (run_start_ts,)
    ).fetchall()
    conn.close()

    print("\n" + "═" * 60)
    print("  MOCK COOJA SIMULATION SUMMARY")
    print("═" * 60)
    print(f"  Duration        : {duration:.0f}s")
    print(f"  Total readings  : {rows_after:,}")
    print(f"  Energy samples  : {energy_after:,}")
    print(f"  Nodes in DB     : {nodes_seen}")
    print(f"  Downlink cmds   : {len(cmd_recv_log)} received")
    print()
    print(f"  {'Node':<12} {'Pkts':>5}  {'Expected':>8}  {'Loss%':>6}  {'Batt start':>10}  {'Batt end':>8}")
    print(f"  {'-'*12} {'-'*5}  {'-'*8}  {'-'*6}  {'-'*10}  {'-'*8}")
    for node_id, pkts, expected, bstart, bend in loss_data:
        loss_pct = (1 - pkts / max(expected, 1)) * 100 if expected else 0
        print(f"  {node_id:<12} {pkts:>5}  {expected:>8}  {loss_pct:>5.1f}%  {bstart:>10}  {bend:>8}")
    print("═" * 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration",       type=float, default=30,
                    help="Simulation duration in seconds (default: 30)")
    ap.add_argument("--collector-port", type=int,   default=8765,
                    help="UDP port the collector is listening on")
    args = ap.parse_args()

    cmd_log, run_start_ts = asyncio.run(
        run_simulation(args.duration, args.collector_port)
    )
    print_summary(cmd_log, args.duration, run_start_ts)


if __name__ == "__main__":
    main()
