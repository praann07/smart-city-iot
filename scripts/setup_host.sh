#!/usr/bin/env bash
###############################################################################
# setup_host.sh — One-shot installer for the Smart City IoT project
#
# Run this in a REAL terminal (not VS Code's Flatpak terminal):
#   cd ~/Desktop/Praneeth-s_files/hi
#   chmod +x scripts/setup_host.sh
#   ./scripts/setup_host.sh
#
# It installs: build-essential, Java 17, Contiki-NG, Cooja, tunslip6,
#              Node.js, Node-RED, and sets up the smart-city example.
###############################################################################
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓] $*${NC}"; }
warn()  { echo -e "${YELLOW}[!] $*${NC}"; }
fail()  { echo -e "${RED}[✗] $*${NC}"; exit 1; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTIKI_DIR="$HOME/contiki-ng"

echo ""
echo "========================================"
echo "  Smart City IoT — Full Setup Script"
echo "========================================"
echo "  Project dir : $PROJECT_DIR"
echo "  Contiki dir : $CONTIKI_DIR"
echo "========================================"
echo ""

# ------------------------------------------------------------------
# Step 1: System packages
# ------------------------------------------------------------------
echo ">>> Step 1/7: Installing system packages..."
sudo apt update -qq
sudo apt install -y \
  build-essential \
  gcc-msp430 \
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
  2>&1 | tail -3

# Verify
command -v gcc     >/dev/null 2>&1 || fail "gcc not found after install"
command -v java    >/dev/null 2>&1 || fail "java not found after install"
command -v make    >/dev/null 2>&1 || fail "make not found after install"
info "System packages installed (gcc, java, make, git, msp430-gcc, sqlite3)"

# ------------------------------------------------------------------
# Step 2: Java version check
# ------------------------------------------------------------------
echo ""
echo ">>> Step 2/7: Checking Java..."
JAVA_VER=$(java -version 2>&1 | head -1 | grep -oP '\d+' | head -1)
if [ "$JAVA_VER" -lt 17 ]; then
  fail "Java 17+ required, found Java $JAVA_VER"
fi
info "Java $JAVA_VER OK"

# ------------------------------------------------------------------
# Step 3: Clone Contiki-NG
# ------------------------------------------------------------------
echo ""
echo ">>> Step 3/7: Setting up Contiki-NG..."
if [ -d "$CONTIKI_DIR/.git" ]; then
  info "Contiki-NG already cloned at $CONTIKI_DIR"
else
  warn "Cloning Contiki-NG (this takes a few minutes)..."
  git clone --recursive https://github.com/contiki-ng/contiki-ng.git "$CONTIKI_DIR"
  info "Contiki-NG cloned"
fi

# Make sure submodules are up to date
cd "$CONTIKI_DIR"
git submodule update --init --recursive 2>&1 | tail -3
info "Submodules updated"

# ------------------------------------------------------------------
# Step 4: Build Cooja
# ------------------------------------------------------------------
echo ""
echo ">>> Step 4/7: Building Cooja simulator..."
cd "$CONTIKI_DIR/tools/cooja"
if [ -f "gradlew" ]; then
  chmod +x gradlew
  # Just build, don't launch
  ./gradlew assemble 2>&1 | tail -5
  info "Cooja built successfully"
else
  fail "gradlew not found in $CONTIKI_DIR/tools/cooja"
fi

# ------------------------------------------------------------------
# Step 5: Copy smart-city nodes into Contiki-NG examples
# ------------------------------------------------------------------
echo ""
echo ">>> Step 5/7: Setting up smart-city example..."
SMART_CITY_DIR="$CONTIKI_DIR/examples/smart-city"
mkdir -p "$SMART_CITY_DIR"

# Copy node source files
cp "$PROJECT_DIR/contiki/nodes/pollution-node.c"    "$SMART_CITY_DIR/"
cp "$PROJECT_DIR/contiki/nodes/temperature-node.c"  "$SMART_CITY_DIR/"
cp "$PROJECT_DIR/contiki/nodes/noise-node.c"        "$SMART_CITY_DIR/"

# Create Makefile if not present
cat > "$SMART_CITY_DIR/Makefile" << 'MKEOF'
CONTIKI_PROJECT = pollution-node temperature-node noise-node
all: $(CONTIKI_PROJECT)

MODULES += os/services/powertrace

CONTIKI = ../..
include $(CONTIKI)/Makefile.include
MKEOF

info "Smart-city nodes copied to $SMART_CITY_DIR"

# Also sync back to project's contiki-ng directory
mkdir -p "$PROJECT_DIR/contiki-ng/examples/smart-city"
cp "$SMART_CITY_DIR/pollution-node.c"    "$PROJECT_DIR/contiki-ng/examples/smart-city/"
cp "$SMART_CITY_DIR/temperature-node.c"  "$PROJECT_DIR/contiki-ng/examples/smart-city/"
cp "$SMART_CITY_DIR/noise-node.c"        "$PROJECT_DIR/contiki-ng/examples/smart-city/"
cp "$SMART_CITY_DIR/Makefile"            "$PROJECT_DIR/contiki-ng/examples/smart-city/"
info "Synced to project's contiki-ng/examples/smart-city/"

# ------------------------------------------------------------------
# Step 6: Build tunslip6
# ------------------------------------------------------------------
echo ""
echo ">>> Step 6/7: Building tunslip6..."
cd "$CONTIKI_DIR/tools/serial-io"
if [ -f "tunslip6.c" ]; then
  make tunslip6 2>&1
  if [ -f "tunslip6" ]; then
    info "tunslip6 built at $CONTIKI_DIR/tools/serial-io/tunslip6"
  else
    warn "tunslip6 build may have failed — check manually"
  fi
else
  warn "tunslip6.c not found; SLIP tunnel must be set up manually"
fi

# ------------------------------------------------------------------
# Step 7: Node.js + Node-RED (optional)
# ------------------------------------------------------------------
echo ""
echo ">>> Step 7/7: Installing Node.js + Node-RED..."
if command -v node >/dev/null 2>&1; then
  info "Node.js already installed: $(node --version)"
else
  warn "Installing Node.js 20 LTS..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>&1 | tail -3
  sudo apt install -y nodejs 2>&1 | tail -3
  info "Node.js $(node --version) installed"
fi

if command -v node-red >/dev/null 2>&1; then
  info "Node-RED already installed"
else
  warn "Installing Node-RED..."
  sudo npm install -g --unsafe-perm node-red 2>&1 | tail -5
  info "Node-RED installed"
fi

# Install Node-RED dashboard nodes
npm install -g node-red-dashboard 2>/dev/null || sudo npm install -g node-red-dashboard 2>&1 | tail -3
info "Node-RED dashboard nodes installed"

# ------------------------------------------------------------------
# Step 8: Python venv setup
# ------------------------------------------------------------------
echo ""
echo ">>> Bonus: Setting up Python venv..."
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install flask pandas scikit-learn numpy matplotlib paho-mqtt joblib -q 2>&1 | tail -3
info "Python venv ready with all dependencies"

# ------------------------------------------------------------------
# Final summary
# ------------------------------------------------------------------
echo ""
echo "========================================"
echo "  ✅  SETUP COMPLETE"
echo "========================================"
echo ""
echo "  Contiki-NG:  $CONTIKI_DIR"
echo "  Cooja:       $CONTIKI_DIR/tools/cooja"
echo "  Smart-city:  $CONTIKI_DIR/examples/smart-city"
echo "  tunslip6:    $CONTIKI_DIR/tools/serial-io/tunslip6"
echo "  Project:     $PROJECT_DIR"
echo ""
echo "  Next steps:"
echo "  1. Open a terminal and run:"
echo "       cd $CONTIKI_DIR/tools/cooja"
echo "       ./gradlew run"
echo "  2. In Cooja: File → Open Simulation → $PROJECT_DIR/SmartCity.csc"
echo "  3. Cooja will compile the 3 node types + border router"
echo "  4. Start the simulation!"
echo ""
echo "  For the backend (in a separate terminal):"
echo "       cd $PROJECT_DIR"
echo "       source .venv/bin/activate"
echo "       python backend/db/init_db.py"
echo "       python backend/ingest/collector.py --port 8765"
echo ""
echo "  For the dashboard:"
echo "       python dashboard/flask_app_stub.py"
echo ""
echo "  For Node-RED:"
echo "       node-red"
echo "       Then import $PROJECT_DIR/dashboard/flows.json"
echo ""
echo "========================================"
