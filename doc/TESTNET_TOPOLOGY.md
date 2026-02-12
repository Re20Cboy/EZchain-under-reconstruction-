# Official MVP Testnet Topology

## Target topology
- `consensus_nodes: 3`
- `bootstrap_nodes: 1`
- fixed network profile for beta users

## Config template (`ezchain.yaml`)

```yaml
network:
  name: testnet
  bootstrap_nodes: ["bootstrap.ezchain.test:19500"]
  consensus_nodes: 3
  account_nodes: 1
  start_port: 19500

app:
  data_dir: .ezchain
  log_dir: .ezchain/logs
  api_host: 127.0.0.1
  api_port: 8787
  api_token_file: .ezchain/api.token

security:
  max_payload_bytes: 65536
  max_tx_amount: 100000000
  nonce_ttl_seconds: 600
```

## Notes
- `api_host` must stay loopback for MVP local-only API surface.
- Wallet password must never be logged.
- Client must send unique `X-EZ-Nonce` and `client_tx_id` for `/tx/send`.
- Use CLI profile switch:
  - `python ezchain_cli.py network set-profile --name local-dev`
  - `python ezchain_cli.py network set-profile --name official-testnet`
