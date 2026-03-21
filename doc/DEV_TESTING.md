# Developer Testing Guide

本指南是开发者提交前和发版前的最小测试标准。

## 1. 环境准备
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 日常开发最小回归（提交前）
1. 核心 + 交易 + V2 分组：
```bash
python run_ezchain_tests.py --groups core transactions v2 --skip-slow
```

2. V2 对抗与鲁棒性强化回归：
```bash
python run_ezchain_tests.py --groups v2-adversarial --skip-slow
```

3. 产品层与脚本测试：
```bash
python scripts/app_gate.py
```

4. 安全门禁：
```bash
python scripts/security_gate.py
```

5. V2 网络分层冒烟检查（可选，但改动账户/共识分离或传输层时建议跑）：
```bash
python3 run_ez_v2_network_smoke.py
python3 run_ez_v2_tcp_network_smoke.py --allow-bind-restricted-skip
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

3. 包含 V2 对抗强化回归（建议 RC / 夜间）：
```bash
python scripts/release_gate.py --skip-slow --with-v2-adversarial
```

4. 同时包含稳定性 + V2 对抗强化回归：
```bash
python scripts/release_gate.py --skip-slow --with-stability --with-v2-adversarial --allow-bind-restricted-skip
```

5. 生成包含 V2 对抗状态的发布报告：
```bash
python scripts/release_report.py --run-gates --with-stability --with-v2-adversarial --allow-bind-restricted-skip
```

6. 触发网络抖动 + 重复请求压力路径（建议 nightly）：
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
  --max-consecutive-failures 0 \
  --max-restart-probe-failures 0 \
  --allow-bind-restricted-skip
```

7. 生成发布报告：
```bash
python scripts/release_report.py --run-gates --with-stability --allow-bind-restricted-skip
```

8. 判断 V2 是否达到“项目默认路径”切换门槛：
```bash
python3 scripts/v2_readiness.py
```

带官方测试网与外部试用记录：
```bash
python scripts/release_report.py \
  --run-gates \
  --with-stability \
  --allow-bind-restricted-skip \
  --require-official-testnet \
  --official-config configs/ezchain.official-testnet.yaml \
  --official-check-connectivity \
  --external-trial-record <trial-record.json>
```

9. 第 6 周灰度观测（可选，发布周建议）：
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
- `scripts/release_gate.py --skip-slow`
  - 内含 `run_ezchain_tests.py --groups core transactions v2 --skip-slow`
  - 内含 `scripts/app_gate.py`
  - 内含 `scripts/security_gate.py`
  - 内含 `run_ez_v2_acceptance.py` 作为 V2 默认路径门槛
- RC/nightly 建议额外执行：
  - `run_ezchain_tests.py --groups v2-adversarial --skip-slow`
  - 或 `scripts/release_gate.py --skip-slow --with-v2-adversarial`
- nightly stability workflow
  - `scripts/stability_gate.py --cycles 30 --interval 1 --restart-every 10 --jitter 0.2 --burst-every 5 --burst-size 3 --max-failures 0 --max-failure-rate 0.0 --max-consecutive-failures 0 --max-restart-probe-failures 0`
  - `run_ezchain_tests.py --groups v2-adversarial --skip-slow`

本地请至少覆盖同等范围，避免“本地通过/CI 失败”。

## 7. 排障建议
1. 先单测失败定位，再跑整组，减少噪声。
2. 配置相关失败优先检查 `ezchain.yaml` 与 profile 是否匹配。
3. 与网络相关的 flake，先用 `local-dev` 复现逻辑，再切 `official-testnet`。
4. 官方测试网外部试用建议先生成一份记录文件，再执行真实演练：
```bash
python scripts/init_external_trial.py \
  --executor your_name \
  --os macos \
  --install-path source
```

生成后按记录文件逐项填写真实结果，并在 RC/发布报告中附带该记录路径。
5. 可先单独校验试用记录：
```bash
python scripts/external_trial_gate.py --record <trial-record.json> --require-passed
```
6. 推荐用脚本更新试用记录，避免手改 JSON：
```bash
python scripts/update_external_trial.py --record <trial-record.json> --step install --step-status passed
```
