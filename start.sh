#!/bin/bash
# start.sh — Start QVAC AI server + Flask project manager
# Usage: ./start.sh [--ai-only] [--web-only] [--download]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

QVAC_PID=""
FLASK_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    [ -n "$QVAC_PID" ] && kill $QVAC_PID 2>/dev/null
    [ -n "$FLASK_PID" ] && kill $FLASK_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

download_model() {
    echo -e "${GREEN}Downloading Qwen 2.5 7B Instruct Q4_K_M from HuggingFace (~4.7GB)...${NC}"
    node -e "
        const { loadModel } = require('@qvac/sdk');
        const url = 'https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf';
        console.log('Downloading from:', url);
        loadModel({
            modelSrc: url,
            modelType: 'llamacpp-completion',
            modelConfig: { ctx_size: 4096 },
            onProgress: (p) => {
                const mb = (p.downloaded / 1024 / 1024).toFixed(0);
                const total = (p.total / 1024 / 1024).toFixed(0);
                if (p.percentage > 0) process.stdout.write('\rProgress: ' + p.percentage.toFixed(1) + '% (' + mb + '/' + total + ' MB)');
            }
        }).then(info => { console.log('\nModel downloaded!'); process.exit(0); })
          .catch(e => { console.error('Error:', e.message); process.exit(1); });
    "
    return $?
}

start_qvac() {
    echo -e "${GREEN}Starting QVAC server with Qwen 2.5 on port 11435...${NC}"
    npx qvac serve openai \
        --config "$SCRIPT_DIR/qvac.config.json" \
        --model qwen2.5 \
        --cors \
        --port 11435 \
        --verbose &
    QVAC_PID=$!
    echo -e "${GREEN}QVAC server starting (PID: $QVAC_PID) on http://localhost:11435${NC}"
    # Wait for server to be ready
    echo -n "Waiting for QVAC server..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:11435/v1/models > /dev/null 2>&1; then
            echo -e "\n${GREEN}QVAC server ready!${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo -e "\n${RED}QVAC server did not start in 30s. It may still be downloading the model.${NC}"
    return 1
}

start_flask() {
    echo -e "${GREEN}Starting Flask project manager...${NC}"
    source "$SCRIPT_DIR/venv/bin/activate" 2>/dev/null || true
    # Use QVAC server on port 11435
    export AI_API_BASE="http://localhost:11435/v1"
    export AI_MODEL="qwen2.5"
    export AI_API_KEY="not-needed"
    python "$SCRIPT_DIR/run.py" &
    FLASK_PID=$!
    echo -e "${GREEN}Flask server starting (PID: $FLASK_PID) on http://localhost:5000${NC}"
}

# Handle arguments
case "${1:-}" in
    --download)
        download_model
        exit $?
        ;;
    --ai-only)
        start_qvac
        echo -e "${YELLOW}QVAC server running. Press Ctrl+C to stop.${NC}"
        wait $QVAC_PID
        ;;
    --web-only)
        start_flask
        echo -e "${YELLOW}Flask server running. Press Ctrl+C to stop.${NC}"
        wait $FLASK_PID
        ;;
    *)
        # Default: start both
        start_qvac
        start_flask
        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  Project Manager is running!${NC}"
        echo -e "${GREEN}  Web:   http://localhost:5000${NC}"
        echo -e "${GREEN}  QVAC:  http://localhost:11435/v1${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo -e "${YELLOW}Press Ctrl+C to stop all servers.${NC}"
        wait
        ;;
esac
