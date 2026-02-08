import argparse
import json
import socket
from typing import Tuple

DEFAULT_PORT = 8765


def send_command(ip: str, port: int, node: str, duty_cycle_pct: int) -> None:
  payload = {
      "type": "cycle_update",
      "node_id": node,
      "duty_cycle_pct": duty_cycle_pct,
  }
  data = json.dumps(payload).encode("utf-8")
  with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
    sock.sendto(data, (ip, port))
    print(f"sent {payload} to {(ip, port)}")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Send duty-cycle update to node via border router")
  parser.add_argument("ip", help="border router IPv6 (e.g., aaaa::1)")
  parser.add_argument("node", help="node_id to target (e.g., poll_03)")
  parser.add_argument("duty", type=int, help="duty cycle percent (0-100)")
  parser.add_argument("--port", type=int, default=DEFAULT_PORT)
  args = parser.parse_args()
  send_command(args.ip, args.port, args.node, args.duty)
