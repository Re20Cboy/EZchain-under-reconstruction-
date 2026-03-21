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

## 文档入口

- 文档总入口：`doc/README.md`
- 项目结构：`doc/PROJECT_STRUCTURE.md`
- 用户快速上手：`doc/USER_QUICKSTART.md`
- 开发测试：`doc/DEV_TESTING.md`
- 发布检查：`doc/RELEASE_CHECKLIST.md`
- 官方测试网试用手册：`doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`

## 当前状态

- V2 已经是默认开发和验证路径
- V1 保留用于兼容和历史参考
- 仓库还不是完整的公网 V2 节点栈
