# Developer Testing Guide

本指南是开发者提交前和发版前的最小测试标准。

## 1. 环境准备
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 日常开发最小回归（提交前）
1. 核心 + 交易分组：
```bash
python run_ezchain_tests.py --groups core transactions --skip-slow
```

2. 产品层与脚本测试：
```bash
pytest -q \
  EZ_Test/test_ez_app_crypto_wallet.py \
  EZ_Test/test_ez_app_config_cli.py \
  EZ_Test/test_ez_app_profiles.py \
  EZ_Test/test_ez_app_network_connectivity.py \
  EZ_Test/test_ez_app_tx_engine.py \
  EZ_Test/test_ez_app_service_api.py \
  EZ_Test/test_ops_backup_restore.py \
  EZ_Test/test_profile_config_script.py
```

3. 安全门禁：
```bash
python scripts/security_gate.py
```

## 3. 发布前门禁（推荐）
1. 统一发布门禁：
```bash
python scripts/release_gate.py --skip-slow
```

2. 包含稳定性门禁：
```bash
python scripts/release_gate.py --skip-slow --with-stability --allow-bind-restricted-skip
```

3. 触发网络抖动 + 重复请求压力路径（建议 nightly）：
```bash
python scripts/stability_gate.py \
  --cycles 30 \
  --interval 1 \
  --restart-every 10 \
  --jitter 0.2 \
  --burst-every 5 \
  --burst-size 3 \
  --max-failures 0 \
  --max-failure-rate 0.0 \
  --allow-bind-restricted-skip
```

4. 生成发布报告：
```bash
python scripts/release_report.py --run-gates --with-stability --allow-bind-restricted-skip
```

5. 第 6 周灰度观测（可选，发布周建议）：
```bash
python scripts/canary_monitor.py --url http://127.0.0.1:8787/metrics --duration-sec 300 --interval-sec 10 --out-json dist/canary_report.json
python scripts/canary_gate.py --report dist/canary_report.json --max-crash-rate 0.05 --min-tx-success-rate 0.95 --max-sync-latency-ms-p95 30000 --min-node-online-rate 0.95 --allow-missing-latency
```

## 4. 官方测试网 profile 校验
```bash
python scripts/testnet_profile_gate.py --config ezchain.yaml
```

带连通性检查：
```bash
python scripts/testnet_profile_gate.py --config ezchain.yaml --check-connectivity
```

## 5. RC 产物流程
```bash
python scripts/prepare_rc.py --version v0.1.0-rc1
python scripts/rc_gate.py
python scripts/release_candidate.py --version v0.1.0-rc1 --with-stability --allow-bind-restricted-skip --target none
```

## 6. CI 对齐说明
CI 当前固定执行：
- `run_ezchain_tests.py --groups core transactions --skip-slow`
- EZ_App 关键 pytest 集合
- `scripts/security_gate.py`

本地请至少覆盖同等范围，避免“本地通过/CI 失败”。

## 7. 排障建议
1. 先单测失败定位，再跑整组，减少噪声。
2. 配置相关失败优先检查 `ezchain.yaml` 与 profile 是否匹配。
3. 与网络相关的 flake，先用 `local-dev` 复现逻辑，再切 `official-testnet`。
