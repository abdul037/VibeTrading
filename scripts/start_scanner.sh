#!/usr/bin/env bash
# Start the daily market scanner daemon.
# Reads Alpaca credentials from ~/.vibe-trading/alpaca.json
# Runs scan at 9:30 AM ET daily, queues proposals in TAP.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"

# Load Alpaca creds
ALPACA_JSON="$HOME/.vibe-trading/alpaca.json"
if [ ! -f "$ALPACA_JSON" ]; then
  echo "❌ Alpaca credentials not found at $ALPACA_JSON"
  exit 1
fi

export ALPACA_API_KEY=$(python3 -c "import json; print(json.load(open('$ALPACA_JSON'))['api_key'])")
export ALPACA_SECRET_KEY=$(python3 -c "import json; print(json.load(open('$ALPACA_JSON'))['secret_key'])")

# Load agent .env
set -a; source "$REPO/agent/.env" 2>/dev/null || true; set +a

# Default broker: etoro
export SCANNER_BROKER="${SCANNER_BROKER:-etoro}"

echo "🚀 Starting scanner daemon (broker=$SCANNER_BROKER)"
echo "   Proposals will appear at: http://localhost:5899/approvals"

cd "$REPO"
exec .venv-py311/bin/python -m agent.src.scanner.scheduler --daemon
