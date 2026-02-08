#!/bin/bash
# Install all dependencies for the Smart City IoT project
# Run with: pkexec bash /path/to/install_deps.sh

set -e
export DEBIAN_FRONTEND=noninteractive

LOG=/tmp/smartcity_install.log
echo "=== Smart City Dependencies Install ===" | tee "$LOG"
echo "Started: $(date)" | tee -a "$LOG"

echo "[1/4] Updating package lists..." | tee -a "$LOG"
apt-get update >> "$LOG" 2>&1
echo "  Done." | tee -a "$LOG"

echo "[2/4] Installing build tools + Java + utilities..." | tee -a "$LOG"
apt-get install -y \
  build-essential \
  openjdk-21-jdk \
  ant \
  git \
  curl \
  wget \
  python3 \
  python3-pip \
  python3-venv \
  sqlite3 \
  net-tools \
  >> "$LOG" 2>&1
echo "  Done." | tee -a "$LOG"

echo "[3/4] Installing Node.js 20 LTS..." | tee -a "$LOG"
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >> "$LOG" 2>&1
  apt-get install -y nodejs >> "$LOG" 2>&1
  echo "  Node.js installed." | tee -a "$LOG"
else
  echo "  Node.js already installed: $(node --version)" | tee -a "$LOG"
fi

echo "[4/4] Installing Node-RED..." | tee -a "$LOG"
if ! command -v node-red &>/dev/null; then
  npm install -g --unsafe-perm node-red >> "$LOG" 2>&1
  echo "  Node-RED installed." | tee -a "$LOG"
else
  echo "  Node-RED already installed." | tee -a "$LOG"
fi

echo "" | tee -a "$LOG"
echo "=== Verification ===" | tee -a "$LOG"
echo "Java:     $(java --version 2>&1 | head -1)" | tee -a "$LOG"
echo "GCC:      $(gcc --version 2>&1 | head -1)" | tee -a "$LOG"
echo "Make:     $(make --version 2>&1 | head -1)" | tee -a "$LOG"
echo "Ant:      $(ant -version 2>&1)" | tee -a "$LOG"
echo "Node:     $(node --version 2>&1)" | tee -a "$LOG"
echo "NPM:      $(npm --version 2>&1)" | tee -a "$LOG"
echo "Node-RED: $(which node-red 2>&1)" | tee -a "$LOG"
echo "SQLite3:  $(sqlite3 --version 2>&1)" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Finished: $(date)" | tee -a "$LOG"
echo "=== ALL DONE ===" | tee -a "$LOG"
