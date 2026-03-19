#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${1:-$(mktemp -d "${TMPDIR:-/tmp}/ezchain_v2_quickstart.XXXXXX")}"
CONFIG_PATH="$WORK_DIR/ezchain.v2.yaml"
DATA_DIR="$WORK_DIR/.ezchain_v2"
PORT="${EZCHAIN_V2_PORT:-8787}"
SERVICE_PID=""

cleanup() {
  if [[ -n "$SERVICE_PID" ]] && kill -0 "$SERVICE_PID" 2>/dev/null; then
    kill "$SERVICE_PID" 2>/dev/null || true
    wait "$SERVICE_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT

mkdir -p "$WORK_DIR"

cat > "$CONFIG_PATH" <<EOF
network:
  name: testnet
  bootstrap_nodes: ["127.0.0.1:19500"]
  consensus_nodes: 1
  account_nodes: 1
  start_port: 19500

app:
  data_dir: $DATA_DIR
  log_dir: $DATA_DIR/logs
  api_host: 127.0.0.1
  api_port: $PORT
  api_token_file: $DATA_DIR/api.token
  protocol_version: v2

security:
  max_payload_bytes: 65536
  max_tx_amount: 100000000
  nonce_ttl_seconds: 600
EOF

cd "$ROOT_DIR"

python3 ezchain_cli.py --config "$CONFIG_PATH" serve &
SERVICE_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

TOKEN="$(python3 ezchain_cli.py --config "$CONFIG_PATH" auth show-token)"

echo "== wallet create =="
curl -fsS "http://127.0.0.1:$PORT/wallet/create" \
  -H "X-EZ-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"demo","password":"pw123"}'
echo
echo

echo "== faucet =="
curl -fsS "http://127.0.0.1:$PORT/tx/faucet" \
  -H "X-EZ-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password":"pw123","amount":300}'
echo
echo

echo "== balance =="
curl -fsS "http://127.0.0.1:$PORT/wallet/balance" \
  -H "X-EZ-Token: $TOKEN" \
  -H "X-EZ-Password: pw123"
echo
echo

echo "== send =="
curl -fsS "http://127.0.0.1:$PORT/tx/send" \
  -H "X-EZ-Token: $TOKEN" \
  -H "X-EZ-Nonce: nonce-v2-quickstart-0001" \
  -H "Content-Type: application/json" \
  -d '{"password":"pw123","recipient":"0xabc123","amount":50,"client_tx_id":"cid-v2-quickstart-001"}'
echo
echo

echo "== receipts =="
curl -fsS "http://127.0.0.1:$PORT/tx/receipts" \
  -H "X-EZ-Token: $TOKEN" \
  -H "X-EZ-Password: pw123"
echo
echo

echo "== history =="
curl -fsS "http://127.0.0.1:$PORT/tx/history"
echo
echo

echo "== node start =="
curl -fsS "http://127.0.0.1:$PORT/node/start" \
  -H "X-EZ-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"consensus":1,"accounts":1}'
echo
echo

echo "== node status =="
curl -fsS "http://127.0.0.1:$PORT/node/status"
echo
echo

echo "== node stop =="
curl -fsS "http://127.0.0.1:$PORT/node/stop" \
  -H "X-EZ-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
echo
echo

echo "quickstart complete"
echo "config: $CONFIG_PATH"
echo "workdir: $WORK_DIR"
