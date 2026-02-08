#!/bin/bash
# ============================================
# Smart City Dashboard - One-Click Startup
# ============================================
set -e

PROJECT="$HOME/Desktop/Praneeth-s_files/hi"
cd "$PROJECT"

echo "============================================"
echo "  Smart City IoT Dashboard Startup"
echo "============================================"
echo ""

# Step 1: Kill any old processes on our ports
echo "[1/5] Killing old processes..."
sudo fuser -k 5001/tcp 2>/dev/null || true
sudo fuser -k 1880/tcp 2>/dev/null || true
sleep 2
echo "      Done."

# Step 2: Copy flows to Node-RED
echo "[2/5] Copying flows to Node-RED..."
mkdir -p "$HOME/.node-red"
cp "$PROJECT/dashboard/flows.json" "$HOME/.node-red/flows.json"
echo "      Done."

# Step 3: Start Flask API
echo "[3/5] Starting Flask API on port 5001..."
cd "$PROJECT"
python3 dashboard/flask_app_stub.py > /tmp/flask.log 2>&1 &
FLASK_PID=$!
echo "      Flask PID: $FLASK_PID"

# Wait for Flask to be ready
echo "      Waiting for Flask..."
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:5001/health > /dev/null 2>&1; then
        echo "      Flask is READY!"
        break
    fi
    sleep 1
done

# Verify Flask works
RESPONSE=$(curl -s http://127.0.0.1:5001/api/metrics/latest 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "FAIL")
if [ "$RESPONSE" = "FAIL" ]; then
    echo "      ERROR: Flask not responding! Check /tmp/flask.log"
    exit 1
fi
echo "      Flask API returns $RESPONSE nodes. OK!"

# Step 4: Start Node-RED
echo "[4/5] Starting Node-RED on port 1880..."
node-red > /tmp/nodered.log 2>&1 &
NODERED_PID=$!
echo "      Node-RED PID: $NODERED_PID"

echo "      Waiting for Node-RED..."
for i in $(seq 1 20); do
    if curl -s http://127.0.0.1:1880 > /dev/null 2>&1; then
        echo "      Node-RED is READY!"
        break
    fi
    sleep 1
done

# Step 5: Summary
echo ""
echo "============================================"
echo "  ALL SERVICES RUNNING!"
echo "============================================"
echo ""
echo "  Flask API:   http://localhost:5001"
echo "  Node-RED:    http://localhost:1880"
echo "  Dashboard:   http://localhost:1880/ui"
echo ""
echo "  API Endpoints:"
echo "    http://localhost:5001/api/metrics/latest"
echo "    http://localhost:5001/api/metrics/series?limit=200"
echo "    http://localhost:5001/api/alerts?pm25=50&noise=90"
echo "    http://localhost:5001/api/predictions"
echo "    http://localhost:5001/api/energy"
echo ""
echo "  IMPORTANT: Open http://localhost:1880 first"
echo "             and click DEPLOY button!"
echo "  Then open: http://localhost:1880/ui"
echo ""
echo "  To stop: kill $FLASK_PID $NODERED_PID"
echo "============================================"

# Keep script alive so bg processes don't die
wait
