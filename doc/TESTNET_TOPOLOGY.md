# Official MVP Testnet Topology

## Target topology
- `consensus_nodes: 3`
- `bootstrap_nodes: 1`
- fixed network profile for beta users

Canonical profile file: `configs/ezchain.official-testnet.yaml`

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
  protocol_version: v2

security:
  max_payload_bytes: 65536
  max_tx_amount: 100000000
  nonce_ttl_seconds: 600
```

## Notes
- Current repository test coverage now includes a smallest realistic cluster rehearsal:
  - `3` consensus nodes
  - `4` account nodes
  - each round randomly chooses one consensus node as the block winner
  - the other two consensus nodes follow and catch up by syncing announced blocks
  - the rehearsal can also force one round into winner-failover mode and verify automatic fallback
  - a late-joining follower can sync several missed blocks before taking a later round
  - a follower that misses several rounds can restart and catch up on the next announced block
  - malicious or broken announcements are also checked: wrong-chain blocks, bad state roots, and fake heights without fetchable blocks must be rejected
- This is a replication-style rehearsal, not a finished multi-proposer public-network consensus implementation.
- `api_host` must stay loopback for MVP local-only API surface.
- Wallet password must never be logged.
- Client must send unique `X-EZ-Nonce` and `client_tx_id` for `/tx/send`.
- Probe bootstrap reachability before tx tests:
  - `python ezchain_cli.py network check`
- Use CLI profile switch:
  - `python ezchain_cli.py network set-profile --name local-dev`
  - `python ezchain_cli.py network set-profile --name official-testnet`
- Or generate a fresh config directly from template:
  - `python scripts/profile_config.py --profile official-testnet --out ezchain.yaml`
- If only one Mac is available, first do a single-host pseudo-remote rehearsal:
  - `python scripts/single_host_testnet_config.py --out ezchain.yaml`
- For a developer-side multi-node cluster rehearsal on one machine:
  - `python3 run_ez_v2_tcp_cluster_smoke.py --allow-bind-restricted-skip`
  - `python3 run_ez_v2_tcp_cluster_smoke.py --allow-bind-restricted-skip --seed 915 --failover-round 2`
