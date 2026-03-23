# EZchain 仓库说明

English README: `README.md`

EZchain 是一个从研究原型走向工程化实现的区块链代码库。  
当前默认路径：**V2**。

现在仓库可以简单理解成三层：

- `EZ_V2/`：V2 协议核心、runtime、localnet、wallet/storage
- `EZ_App/`：CLI、本地 service API、节点生命周期管理
- `EZ_V1/`：冻结的 V1 实现和历史归档

顶层像 `EZ_VPB/`、`EZ_Account/`、`EZ_Transaction/` 这些 V1 目录目前主要是兼容入口，方便旧 import 不断。

## 快速开始

先使用默认 V2 本地配置：

```bash
cp configs/ezchain.v2-localnet.yaml ezchain.yaml
```

创建钱包、领取本地测试值、发起交易：

```bash
python3 ezchain_cli.py --config ezchain.yaml wallet create --password your_password --name default
python3 ezchain_cli.py --config ezchain.yaml tx faucet --amount 1000 --password your_password
python3 ezchain_cli.py --config ezchain.yaml tx send --recipient 0xabc123 --amount 100 --password your_password --client-tx-id cid-001
```

启动本地服务：

```bash
python3 ezchain_cli.py --config ezchain.yaml serve
```

可选：启动一个最小可运行的 V2 TCP 共识节点模式：

```bash
python3 ezchain_cli.py --config ezchain.yaml node start --mode v2-tcp-consensus
python3 ezchain_cli.py --config ezchain.yaml node status
python3 ezchain_cli.py --config ezchain.yaml node stop
```

这个模式只启动一个轻量 V2 共识 daemon，默认绑定
`network.bootstrap_nodes[0]`；如果没有配置 bootstrap endpoint，就回退到
`127.0.0.1:<start_port>`。它是一个可选的开发/节点入口；默认的钱包和
service 路径仍然走本地 V2 runtime。

当前还提供一个最小 `v2-account` 开发模式，用来把账户角色单独拉起来接入
已有共识端点。`node status` 现在会直接显示模式归属、节点角色、共识端点、
账户地址、基础同步计数，以及最近一次同步是否成功。如果这类 V2 节点一启动
就退出，数据目录里还会留下对应的 `*_startup.log` 方便排查。
对于 `v2-account`，状态里现在还会继续保留恢复侧信息：当前连续同步失败次数、
历史最长连续失败次数、上一次成功同步时间，以及失去共识端点后恢复成功的次数。
为了更直观地看状态，现在还会额外给出 `sync_health` 和
`sync_health_reason`，直接告诉你当前是健康、降级，还是刚恢复。
如果你在启动 `v2-account` 之前已经先创建了本地钱包，账户节点现在会优先复用
这个钱包对应的 V2 地址，而不是再单独生成一套新地址。
如果这个钱包文件存在，账户节点现在还会继续复用对应的
`wallet_state_v2/<address>/wallet_v2.db`，这样后面补远端交易路径时，CLI 和
账户节点至少能站在同一份 V2 钱包状态上。

如果你当前运行的是 `v2-account`，还可以直接查看账户节点专用状态：

```bash
python3 ezchain_cli.py --config ezchain.yaml node account-status
```

如果是 `official-testnet + v2`，当前能力边界也已经说得更直白了：

- `wallet balance`、`wallet checkpoints`、`tx pending`、`tx receipts`、`tx history`
  这类只读查询，可以直接读共享的钱包库和本地 history 状态
- `tx send` 现在只要你明确提供收款方账户节点地址，或者提前把它记进本地地址簿，就能走远端账户路径
- `tx faucet` 还没有接成远端路径

示例：

```bash
python3 ezchain_cli.py --config ezchain.yaml contacts set \
  --address 0xabc123 \
  --endpoint 192.168.1.20:19500

python3 ezchain_cli.py --config ezchain.yaml tx send \
  --recipient 0xabc123 \
  --amount 100 \
  --password your_password \
  --client-tx-id cid-remote-001
```

如果对方已经跑起了 `v2-account`，现在也可以直接导出一张联系卡，不用手抄地址和端口：

```bash
python3 ezchain_cli.py --config ezchain.yaml contacts export-self --out bob-contact.json
python3 ezchain_cli.py --config ezchain.yaml contacts import-card --file bob-contact.json
```

如果对方已经开了本地服务，你现在也可以直接从对方服务地址抓联系卡，再顺手导入：

```bash
python3 ezchain_cli.py --config ezchain.yaml contacts fetch-card \
  --url http://192.168.1.20:8787 \
  --out bob-contact.json \
  --import-to-contacts
```

如果你想检查本地到底已经记了哪些收款节点，服务侧现在也有只读查看口：

- `GET /contacts`
- `GET /contacts/<address>`

现在地址簿已经有一整套最小闭环：

- 手动新增：`contacts set`
- 查看单条：`contacts show`
- 查看全部：`contacts list` 或 `GET /contacts`
- 导出自己：`contacts export-self`
- 从文件导入：`contacts import-card`
- 从服务抓取：`contacts fetch-card`
- 服务侧写入 / 导入 / 抓取 / 删除：`POST /contacts`、`POST /contacts/import-card`、`POST /contacts/fetch-card`、`DELETE /contacts/<address>`

## 主要入口

- CLI：`ezchain_cli.py`
- 本地服务：`EZ_App/service.py`
- V2 本地运行时：`EZ_V2/runtime_v2.py`
- V2 本地网络：`run_ez_v2_localnet.py`
- 轻量 V2 TCP 共识节点：`run_ez_v2_tcp_consensus.py`
- 验收入口：`run_ez_v2_acceptance.py`

## 验证命令

推荐本地检查：

```bash
python3 run_ezchain_tests.py --groups v2 --skip-slow
python3 run_ezchain_tests.py --groups v2-adversarial --skip-slow
python3 run_ez_v2_acceptance.py
```

发布级门禁：

```bash
python3 scripts/release_gate.py --skip-slow --with-stability --with-v2-adversarial
```

readiness 级报告：

```bash
python3 scripts/release_report.py --run-gates --with-stability --with-consensus --with-v2-adversarial --allow-bind-restricted-skip
python3 scripts/v2_readiness.py
```

现在报告会明确区分两件事：

- 分层共识验证是否已经通过
- 当前环境里是否真的执行并形成了 TCP 共识正式证据

## 文档入口

- 文档总入口：`doc/README.md`
- 项目结构：`doc/PROJECT_STRUCTURE.md`
- 用户快速上手：`doc/USER_QUICKSTART.md`
- 开发测试：`doc/DEV_TESTING.md`
- 发布检查：`doc/RELEASE_CHECKLIST.md`
- 官方测试网试用手册：`doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`

## 当前状态

- V2 已经是默认开发和验证路径
- V2 是否已经达到默认正式交付口径，仍以 readiness 和真实官方测试网最终确认为准
- `consensus_gate` 通过现在表示分层共识套件已通过，不自动等同于 TCP 多节点正式证据已经形成
- `release_report` 和 `v2_readiness` 现在会单独给出 TCP 共识证据状态，包括当前机器因 bind 限制没有执行 TCP 套件的情况
- V1 保留用于兼容和历史参考
- 仓库还不是完整的公网 V2 节点栈
