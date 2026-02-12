# EZchain 中文说明

> English README: `README.md`

这个版本只讲三件事：
1. 项目现在能做什么。
2. 你怎么在本地跑起来。
3. 开发/发布前最低要做哪些检查。

## 1. 当前项目状态
- 当前定位：`MVP 可试用阶段`（测试网，不是主网）。
- 产品入口：`ezchain_cli.py`（CLI 主入口）+ 本地服务 API（loopback）。
- 已具备：钱包创建/导入、余额/历史、转账、节点启动/状态、基础发布门禁、RC 工具链。
- 详细状态：`doc/PROJECT_CHECKPOINT_2026-02-12.md`

## 2. 5 分钟快速开始
### 2.1 环境准备
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.2 生成配置（官方测试网）
```bash
python scripts/profile_config.py --profile official-testnet --out ezchain.yaml
python ezchain_cli.py network info
```

### 2.3 创建钱包并领取测试资金
```bash
python ezchain_cli.py wallet create --password your_password --name default
python ezchain_cli.py tx faucet --amount 1000 --password your_password
python ezchain_cli.py wallet balance --password your_password
```

### 2.4 发起一笔交易
```bash
python ezchain_cli.py tx send --recipient 0xabc123 --amount 100 --password your_password
python ezchain_cli.py wallet show
```

## 3. 常用命令
### 钱包
```bash
python ezchain_cli.py wallet create --password your_password --name default
python ezchain_cli.py wallet import --password your_password --mnemonic "..."
python ezchain_cli.py wallet show
python ezchain_cli.py wallet balance --password your_password
```

### 节点与网络
```bash
python ezchain_cli.py node start --consensus 1 --accounts 1 --start-port 19500
python ezchain_cli.py node status
python ezchain_cli.py node stop
python ezchain_cli.py network check
```

### 本地 API
```bash
python ezchain_cli.py serve
python ezchain_cli.py auth show-token
```

## 4. 开发者最低要求
```bash
python run_ezchain_tests.py --groups core transactions --skip-slow
python scripts/security_gate.py
python scripts/release_gate.py --skip-slow
```

如果要做发布演练：
```bash
python scripts/release_candidate.py --version v0.1.0-rc1 --with-stability --allow-bind-restricted-skip --run-canary --target none
```

## 5. 发布与灰度
- 灰度观测采样：`scripts/canary_monitor.py`
- 灰度阈值门禁：`scripts/canary_gate.py`
- RC/报告工具：`scripts/release_candidate.py`、`scripts/release_report.py`

推荐看：
- `doc/RELEASE_CHECKLIST.md`
- `doc/MVP_RUNBOOK.md`

## 6. 文档导航
- 文档总入口：`doc/README.md`
- 用户快速上手：`doc/USER_QUICKSTART.md`
- 开发测试指南：`doc/DEV_TESTING.md`
- 安装指南：`doc/INSTALLATION.md`
- 错误码：`doc/API_ERROR_CODES.md`

## 7. 当前边界（注意）
- 默认是测试网流程，不是主网发布。
- 本地 API 只面向 loopback，不建议暴露公网。
- 并发场景下已做重放/重复交易防护，但复杂业务行为仍以门禁脚本与回归测试为准。
