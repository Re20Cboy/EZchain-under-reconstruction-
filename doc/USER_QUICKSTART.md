# User Quickstart (MVP)

本指南面向终端试用用户，目标是在本地快速完成钱包创建、收款、转账、查询。

## 1. 安装
优先参考：`doc/INSTALLATION.md`

如果这次是为了形成正式试用记录，而不是个人临时体验，优先同时参考：

- `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`

最简流程（源码运行）：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 生成配置并切换官方测试网
推荐直接生成官方 profile：
```bash
python scripts/profile_config.py --profile official-testnet --out ezchain.yaml
```

如果你只有一台 Mac，没有第二台远端设备，可先用“单机伪远端”替代办法：

```bash
python scripts/single_host_testnet_config.py --out ezchain.yaml
python ezchain_cli.py --config ezchain.yaml wallet create --password your_password --name default
python run_ez_v2_tcp_consensus.py \
  --root-dir .ezchain_remote_consensus \
  --state-file .ezchain_remote_consensus/state.json \
  --chain-id 1 \
  --endpoint 0.0.0.0:19500
python ezchain_cli.py --config ezchain.yaml node start --mode v2-account
python ezchain_cli.py --config ezchain.yaml node account-status
```

这条路的作用很直接：

- 先验证端口、局域网 IP、配置、连通性检查有没有问题
- 先验证账户节点能不能接上共识节点
- 如果你先建钱包，再起 `v2-account`，账户节点会直接复用这个钱包的 V2 地址

但它不是最终正式测试网证明，因为你还是只用了同一台机器。

查看网络信息：
```bash
python ezchain_cli.py network info
python ezchain_cli.py network check
```

如果这里看到：

- `mode = official-testnet`
- `tx_path_ready = false`

意思很简单：

- 远端 profile 这层已经生效
- 但交易命令现在还没真正走远端账户节点

为了避免混淆，当前 `official-testnet + v2` 下的交易相关命令会直接返回
`tx_path_not_ready`，而不是再悄悄给出本地运行时结果。

但如果你已经启动了 `v2-account`，而且它复用了当前钱包对应的共享 V2 钱包库，
下面这些只读命令现在已经可以先用：

- `python ezchain_cli.py wallet balance --password your_password`
- `python ezchain_cli.py wallet checkpoints --password your_password`
- `python ezchain_cli.py tx pending --password your_password`
- `python ezchain_cli.py tx receipts --password your_password`

另外，`tx send` 现在也补了一条最小可用路，但条件更明确：

- 只在 `v2-account` 已运行时可用
- 你要么显式提供收款方账户节点地址，要么提前把它记进本地地址簿

示例：

```bash
python ezchain_cli.py contacts set \
  --address 0xabc123 \
  --endpoint 192.168.1.20:19500

python ezchain_cli.py tx send \
  --recipient 0xabc123 \
  --amount 100 \
  --password your_password
```

如果你既拿不到收款方账户节点地址，也没有提前保存过它，这条远端发送路径就先不要当成可用。

如果对方已经跑着 `v2-account`，更省事的做法是让对方直接导出一张联系卡：

```bash
python ezchain_cli.py contacts export-self --out bob-contact.json
python ezchain_cli.py contacts import-card --file bob-contact.json
```

导入后，这个地址就会记进本地地址簿，后面 `tx send` 可以直接复用。

如果对方已经开了服务，也可以直接从服务地址拉联系卡：

```bash
python ezchain_cli.py contacts fetch-card \
  --url http://192.168.1.20:8787 \
  --out bob-contact.json \
  --import-to-contacts
```

如果你想确认本地地址簿里到底存了哪些收款节点，可以直接查服务接口：

- `GET /contacts`
- `GET /contacts/<address>`

如果你想在本地终端里直接查，也可以用：

- `python ezchain_cli.py contacts list`
- `python ezchain_cli.py contacts show --address 0xabc123`

如果这是正式试用，建议顺手把这张联系卡也记进试用记录，别只留命令输出。

如果你不想手动分三步做，现在也可以直接用：

```bash
python scripts/official_testnet_send_rehearsal.py \
  --config ezchain.yaml \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --password your_password \
  --contact-card-file bob-contact.json \
  --amount 100
```

如果要为发布准备证据，建议先初始化试用记录：

```bash
python scripts/init_external_trial.py --executor your_name --os macos --install-path source
```

后续每做完一步，都可以用：

```bash
python scripts/update_external_trial.py --record <trial-record.json> --auto-status
```

它会直接告诉你这份记录现在是通过、失败，还是还没做完，以及还差哪几步。

## 3. 创建钱包
```bash
python ezchain_cli.py wallet create --password your_password --name default
```

说明：输出中会包含助记词，请离线安全保存。

## 4. 领取测试资金并转账
先领取测试资金：
```bash
python ezchain_cli.py tx faucet --amount 1000 --password your_password
```

查看余额：
```bash
python ezchain_cli.py wallet balance --password your_password
```

发起转账：
```bash
python ezchain_cli.py tx send --recipient 0xabc123 --amount 100 --password your_password
```

查看历史：
```bash
python ezchain_cli.py wallet show
```

## 5. 启动本地服务（可选）
```bash
python ezchain_cli.py serve
```

查看 API token：
```bash
python ezchain_cli.py auth show-token
```

如果本机支持浏览器访问：
```bash
open http://127.0.0.1:8787/ui
```

## 6. 升级前备份（强烈建议）
```bash
python scripts/ops_backup.py --config ezchain.yaml --out-dir backups --label pre-upgrade
```

回滚恢复：
```bash
python scripts/ops_restore.py --backup-dir backups/<snapshot-dir> --config ezchain.yaml --force
```

## 常见问题
1. `network check` 不通：检查网络、DNS、代理策略；可先切回 `local-dev` 验证本地能力。
2. `tx send` 报参数错误：按 `doc/API_ERROR_CODES.md` 对照字段修复。
3. 忘记备份：先停止服务，再手动备份 `ezchain.yaml` 和数据目录后再升级。
4. 如果这是一次正式外部试用，请按 `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md` 填写记录，而不是只保留命令输出。
