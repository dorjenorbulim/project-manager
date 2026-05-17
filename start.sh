#!/bin/bash
# start.sh — Start Flask project manager
# Usage: ./start.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Starting Flask project manager...${NC}"
source "$SCRIPT_DIR/venv/bin/activate" 2>/dev/null || true
python "$SCRIPT_DIR/run.py" &
FLASK_PID=$!
echo -e "${GREEN}Flask server starting (PID: $FLASK_PID) on http://localhost:5000${NC}"

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    [ -n "$FLASK_PID" ] && kill $FLASK_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Project Manager is running!${NC}"
echo -e "${GREEN}  Web:   http://localhost:5000${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop.${NC}"
wait
