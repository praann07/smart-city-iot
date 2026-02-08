#!/bin/bash
###############################################################################
# Smart City IoT — Demo Launcher
#
# USE: Open 5 separate terminals and run each step in order.
#
#   Terminal 1:  bash scripts/run_demo.sh cooja
#   Terminal 2:  bash scripts/run_demo.sh tunnel
#   Terminal 3:  bash scripts/run_demo.sh backend
#   Terminal 4:  bash scripts/run_demo.sh dashboard
#   Terminal 5:  bash scripts/run_demo.sh monitor
#
#   To stop:     bash scripts/run_demo.sh stop
###############################################################################

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTIKI_DIR="$HOME/contiki-ng"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   🏙  Smart City IoT Demo — TEAM-10             ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
}

case "${1:-help}" in

cooja)
    banner
    echo -e "${GREEN}${BOLD}▶ STEP 1: Launching Cooja Simulator${NC}"
    echo ""
    echo -e "  ${YELLOW}When Cooja opens:${NC}"
    echo "    1. File → Open Simulation → SmartCity.csc"
    echo "       Path: $CONTIKI_DIR/examples/smart-city/SmartCity.csc"
    echo "    2. Click START to begin simulation"
    echo "    3. Show the RPL tree in Network Visualizer"
    echo "    4. Show PowerTracker plugin"
    echo ""
    echo -e "  ${CYAN}Starting Cooja...${NC}"
    cd "$CONTIKI_DIR/tools/cooja" && ./gradlew run
    ;;

tunnel)
    banner
    echo -e "${GREEN}${BOLD}▶ STEP 2: Starting Border Router Tunnel${NC}"
    echo ""
    echo "  This connects the simulated sensor network to your PC."
    echo "  Make sure Cooja is running and simulation is started first!"
    echo ""
    echo -e "  ${CYAN}Starting tunslip6...${NC}"
    sudo "$CONTIKI_DIR/tools/serial-io/tunslip6" -a 127.0.0.1 -p 60003 aaaa::1/64
    ;;

backend)
    banner
    echo -e "${GREEN}${BOLD}▶ STEP 3: Starting Backend (Collector + Flask API)${NC}"
    echo ""
    cd "$PROJECT_DIR"

    # Init DB if needed
    if [ ! -f backend/db/iot.db ]; then
        echo "  Initializing database..."
        python3 backend/db/init_db.py
    fi

    echo -e "  ${GREEN}✓ Starting UDP collector on port 8765...${NC}"
    python3 backend/ingest/collector.py &
    COLLECTOR_PID=$!

    sleep 1
    echo -e "  ${GREEN}✓ Starting Flask API on port 5001...${NC}"
    python3 dashboard/flask_app_stub.py &
    FLASK_PID=$!

    echo ""
    echo -e "  ${BOLD}Collector PID:${NC} $COLLECTOR_PID"
    echo -e "  ${BOLD}Flask PID:${NC}     $FLASK_PID"
    echo ""
    echo -e "  ${CYAN}API Endpoints (open in Firefox):${NC}"
    echo "    http://localhost:5001/health"
    echo "    http://localhost:5001/api/metrics/latest"
    echo "    http://localhost:5001/api/predictions"
    echo "    http://localhost:5001/api/energy"
    echo "    http://localhost:5001/api/alerts?pm25=100&noise=80"
    echo ""
    echo -e "  ${YELLOW}Press Ctrl+C to stop...${NC}"
    wait
    ;;

dashboard)
    banner
    echo -e "${GREEN}${BOLD}▶ STEP 4: Starting Node-RED Dashboard${NC}"
    echo ""
    
    # Copy flows if not present
    if [ ! -f "$HOME/.node-red/flows.json" ]; then
        mkdir -p "$HOME/.node-red"
        cp "$PROJECT_DIR/dashboard/flows.json" "$HOME/.node-red/flows.json"
        echo "  Imported flows.json"
    fi

    echo -e "  ${CYAN}Dashboard:${NC}  http://localhost:1880/ui"
    echo -e "  ${CYAN}Editor:${NC}     http://localhost:1880"
    echo ""
    node-red
    ;;

monitor)
    banner
    echo -e "${GREEN}${BOLD}▶ STEP 5: Live Data Monitor${NC}"
    echo ""
    cd "$PROJECT_DIR"
    python3 scripts/live_monitor.py
    ;;

stop)
    banner
    echo -e "${RED}${BOLD}▶ Stopping all services...${NC}"
    pkill -f "collector.py" 2>/dev/null && echo "  ✗ Collector stopped" || echo "  - Collector not running"
    pkill -f "flask_app_stub.py" 2>/dev/null && echo "  ✗ Flask stopped" || echo "  - Flask not running"
    pkill -f "node-red" 2>/dev/null && echo "  ✗ Node-RED stopped" || echo "  - Node-RED not running"
    pkill -f "tunslip6" 2>/dev/null && echo "  ✗ tunslip6 stopped" || echo "  - tunslip6 not running"
    echo -e "${GREEN}  Done.${NC}"
    ;;

*)
    banner
    echo -e "${BOLD}DEMO ORDER — Open 5 terminals and run in this sequence:${NC}"
    echo ""
    echo -e "  ${GREEN}Terminal 1:${NC}  bash scripts/run_demo.sh ${BOLD}cooja${NC}"
    echo "              → Cooja opens. Load SmartCity.csc → Click Start"
    echo ""
    echo -e "  ${GREEN}Terminal 2:${NC}  bash scripts/run_demo.sh ${BOLD}tunnel${NC}"
    echo "              → Connects border router (needs sudo password)"
    echo ""
    echo -e "  ${GREEN}Terminal 3:${NC}  bash scripts/run_demo.sh ${BOLD}backend${NC}"
    echo "              → Starts collector + Flask API"
    echo ""
    echo -e "  ${GREEN}Terminal 4:${NC}  bash scripts/run_demo.sh ${BOLD}dashboard${NC}"
    echo "              → Node-RED dashboard at localhost:1880/ui"
    echo ""
    echo -e "  ${GREEN}Terminal 5:${NC}  bash scripts/run_demo.sh ${BOLD}monitor${NC}"
    echo "              → Live stats updating on screen"
    echo ""
    echo -e "  ${RED}Stop all:${NC}    bash scripts/run_demo.sh ${BOLD}stop${NC}"
    echo ""
    ;;
esac
