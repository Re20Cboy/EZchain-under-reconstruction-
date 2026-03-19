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

## 5. 开发验证入口

本地 smoke：

```bash
python3 run_ez_v2_localnet.py --chain-id 702
```

阶段 4 验收：

```bash
python3 run_ez_v2_acceptance.py
```
