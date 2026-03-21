# EZchain V2 Quickstart

## 1. 最小配置

创建 `ezchain.yaml`，至少包含：

```yaml
network:
  name: testnet
  bootstrap_nodes: ["127.0.0.1:19500"]
  consensus_nodes: 1
  account_nodes: 1
  start_port: 19500

app:
  data_dir: .ezchain_v2
  log_dir: .ezchain_v2/logs
  api_host: 127.0.0.1
  api_port: 8787
  api_token_file: .ezchain_v2/api.token
  protocol_version: v2

security:
  max_payload_bytes: 65536
  max_tx_amount: 100000000
  nonce_ttl_seconds: 600
```

## 2. CLI 最小流程

```bash
python3 ezchain_cli.py --config ezchain.yaml wallet create --name demo --password pw123
python3 ezchain_cli.py --config ezchain.yaml tx faucet --amount 300 --password pw123
python3 ezchain_cli.py --config ezchain.yaml tx send --recipient 0xabc123 --amount 50 --password pw123 --client-tx-id cid-001
python3 ezchain_cli.py --config ezchain.yaml wallet balance --password pw123
python3 ezchain_cli.py --config ezchain.yaml tx receipts --password pw123
python3 ezchain_cli.py --config ezchain.yaml tx history
```

## 3. HTTP Service 最小流程

启动服务：

```bash
python3 ezchain_cli.py --config ezchain.yaml serve
```

查看 token：

```bash
python3 ezchain_cli.py --config ezchain.yaml auth show-token
```

然后按顺序调用：

1. `POST /wallet/create`
2. `POST /tx/faucet`
3. `GET /wallet/balance`
4. `POST /tx/send`
5. `GET /tx/receipts`
6. `GET /tx/history`

注意：

- 写接口需要 `X-EZ-Token`
- 敏感查询接口需要 `X-EZ-Password`
- `POST /tx/send` 需要 `X-EZ-Nonce`

## 4. 一键脚本

仓库里已经提供：

```bash
./scripts/run_v2_service_quickstart.sh
```

它会自动：

1. 生成临时 V2 配置
2. 启动本地 service
3. 创建钱包
4. faucet
5. 发送一笔交易
6. 查询 balance / receipts / history
7. 演示 `node start/status/stop`

如果你想指定工作目录：

```bash
./scripts/run_v2_service_quickstart.sh /tmp/ezchain_v2_demo
```

## 5. 轻量 TCP 共识节点模式（可选）

如果你要跑最小真实 TCP 节点入口，而不是本地 shared localnet，可直接用：

```bash
python3 ezchain_cli.py --config ezchain.yaml node start --mode v2-consensus
python3 ezchain_cli.py --config ezchain.yaml node status
python3 ezchain_cli.py --config ezchain.yaml node stop
```

说明：

- 这是当前最小的 network-backed V2 节点模式，只启动单个共识 daemon
- 钱包和 HTTP service 路径不变，仍然走 `python3 ezchain_cli.py --config ezchain.yaml serve`
- 默认监听 `network.bootstrap_nodes[0]`；如果配置为空，则回退到 `127.0.0.1:<start_port>`
- 当前故意保持静态 endpoint、单节点、最小状态面，优先减少传输、存储和验证开销，适合作为消费级主机上的 V2 节点验证入口
- `node status` 现在会直接告诉你当前模式归属和节点角色；如果是 `v2-account`，还会显示它连接的共识端点、账户地址、几项最基础的同步计数，以及最近一次同步是否成功
- `v2-account` 状态现在还会带：
  - 当前连续同步失败次数
  - 历史最长连续失败次数
  - 上一次成功同步时间
  - 恢复次数
  - 上一次恢复时间
- 同时还会给一组更直白的判断：
  - `sync_health`
  - `sync_health_reason`
  例如 `healthy`、`degraded`、`recovered`
- 如果当前运行的是 `v2-account`，可直接用 `python3 ezchain_cli.py --config ezchain.yaml node account-status` 查看账户节点专用状态
- 如果 `v2-account` 或 `v2-consensus` 一启动就退出，App 层现在会把启动报错留到数据目录里的 `*_startup.log` 文件里，并把最后几行错误直接带进返回信息，方便第一时间排查
- 如果你想验证“账户角色”和“共识角色”分离，当前还提供一个最小 `v2-account` 开发骨架模式；它主要用于角色拆分验证，不是默认用户钱包入口

## 6. 开发验证入口

本地 smoke：

```bash
python3 run_ez_v2_localnet.py --chain-id 702
```

阶段 4 验收：

```bash
python3 run_ez_v2_acceptance.py
```
