# EZchain 仓库说明

> English README: `README.md`

这个仓库现在处于 **V1 向 V2 迁移** 的阶段。  
当前推荐使用的是 **V2 本地运行路径**，而不是旧的 V1 协议主路径。

## 当前状态

- `EZ_V2` 已经可以支撑本地钱包、local runtime、localnet、service API 和 acceptance gate
- `V1` 相关模块仍保留在仓库中，但已经进入 `legacy / freeze` 准备阶段
- 推荐本地配置模板：`configs/ezchain.v2-localnet.yaml`
- 推荐验收入口：`python3 run_ez_v2_acceptance.py`

V1 freeze / V2 默认切换规则见：
- `EZchain-V2-design/EZchain-V1-freeze-and-V2-default-transition.md`

## 推荐快速开始

先使用 V2 本地配置：

```bash
cp configs/ezchain.v2-localnet.yaml ezchain.yaml
```

创建钱包、领取本地测试值、发起一笔交易：

```bash
python3 ezchain_cli.py --config ezchain.yaml wallet create --password your_password --name default
python3 ezchain_cli.py --config ezchain.yaml tx faucet --amount 1000 --password your_password
python3 ezchain_cli.py --config ezchain.yaml wallet balance --password your_password
python3 ezchain_cli.py --config ezchain.yaml tx send --recipient 0xabc123 --amount 100 --password your_password --client-tx-id cid-001
python3 ezchain_cli.py --config ezchain.yaml tx receipts --password your_password
```

启动本地 API：

```bash
python3 ezchain_cli.py --config ezchain.yaml serve
```

查看本地 API token：

```bash
python3 ezchain_cli.py --config ezchain.yaml auth show-token
```

一键跑通 V2 service 演示：

```bash
./scripts/run_v2_service_quickstart.sh
```

## 仓库结构

### 当前主路径

- `EZ_V2/`
  - V2 协议核心、钱包存储、validator、runtime、localnet、control plane
- `EZ_App/`
  - CLI、本地 HTTP API、运行时桥接、节点生命周期管理
- `configs/`
  - 配置模板
- `scripts/`
  - quickstart、发布门禁、运维工具
- `EZ_Test/`
  - 测试集，包含 V2 acceptance 和 runtime 测试
- `doc/`
  - 当前用户/开发/发布/运维文档
- `EZchain-V2-design/`
  - V2 设计文档、路线图、迁移与 freeze 文档

### Legacy / 冻结路径

- `EZ_VPB/`
- `EZ_VPB_Validator/`
- `EZ_Tx_Pool/`
- `EZ_Main_Chain/`
- `EZ_Account/`
- `EZ_Transaction/`

这些 V1 目录目前还保留，用于：

- 历史参考
- 行为对照
- 兼容性比较

但新的协议功能默认不应继续落到这些目录里。

更清晰的结构图见：
- `doc/PROJECT_STRUCTURE.md`

## 主要入口

- CLI 入口：`ezchain_cli.py`
- 应用运行时：`EZ_App/runtime.py`
- 本地服务：`EZ_App/service.py`
- 节点管理：`EZ_App/node_manager.py`
- V2 本地运行时与 localnet：
  - `EZ_V2/runtime_v2.py`
  - `EZ_V2/localnet.py`
  - `run_ez_v2_localnet.py`
- V2 验收入口：`run_ez_v2_acceptance.py`

## 测试与门禁

查看统一测试分组：

```bash
python3 run_ezchain_tests.py --list
```

当前推荐本地回归：

```bash
python3 run_ezchain_tests.py --groups core transactions v2 --skip-slow
python3 run_ez_v2_acceptance.py
```

发布门禁：

```bash
python3 scripts/release_gate.py --skip-slow
python3 scripts/release_gate.py --skip-slow --with-stability
```

## 文档导航

- 文档总入口：`doc/README.md`
- 项目结构：`doc/PROJECT_STRUCTURE.md`
- V2 快速上手：`doc/EZchain-V2-quickstart.md`
- 开发测试：`doc/DEV_TESTING.md`
- 发布检查：`doc/RELEASE_CHECKLIST.md`
- 运行手册：`doc/MVP_RUNBOOK.md`
- V1 freeze / V2 切换：`EZchain-V2-design/EZchain-V1-freeze-and-V2-default-transition.md`
- V2 路线图：`EZchain-V2-design/EZchain-V2-implementation-roadmap.md`

## 研究背景

- 已发表论文（VWchain）：https://www.sciencedirect.com/science/article/abs/pii/S1383762126000512
- 原始白皮书：https://arxiv.org/abs/2312.00281v1
- 原型模拟器：https://github.com/Re20Cboy/Ezchain-py

## 说明

- 这个仓库目前还不是完整的公网 V2 节点栈
- 当前最稳定的路径是本地 V2 runtime / localnet 路径
- 现在优先做的是“结构梳理 + 默认路径切换”，不是立即大规模删除 V1 代码
