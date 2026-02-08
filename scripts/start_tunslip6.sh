#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/start_tunslip6.sh <tty_port> [PREFIX]
# Example: ./scripts/start_tunslip6.sh 60001 aaaa::1/64
# <tty_port> is the TCP port from Cooja Serial Socket or the pty path if using serial2pty.

PORT=${1:-}
PREFIX=${2:-aaaa::1/64}
if [[ -z "$PORT" ]]; then
  echo "Usage: $0 <tty_port> [prefix]" >&2
  exit 1
fi

# If you have a pty path (e.g., /tmp/ttyCOOJA), use -s <path> instead of -p.
CMD=(sudo ./tunslip6 -v2 -a 127.0.0.1 -p "$PORT" "$PREFIX")
echo "Running: ${CMD[*]}"
"${CMD[@]}"
