# V2 Default Readiness

本文件定义“V2 什么时候可以从推荐路径，升级为项目默认路径”。

先把口径说清楚：

- **当前仓库已经把 V2 作为默认开发、默认验证、默认 RC 判断路径**
- **本文件讨论的是更严格的一层：V2 什么时候可以被当作默认正式交付路径**

所以：

- “V2 主线已经切过去”这件事，当前已经成立
- “V2 是否已经收口到默认正式交付路径”这件事，仍以 readiness 条件为准

## 目标

避免项目长期停留在：

- `V2 已经能跑`
- `但团队仍然不敢默认使用`
- `V1/V2 双轨长期并存`

V2 默认化不是一句口头判断，而是一组必须满足的项目级条件。

## 必须满足的条件

1. `release_report` 总体通过
   - 说明当前候选版本已经通过统一发布检查。
2. `v2_gate_status = passed`
   - 说明默认 V2 回归、V2 acceptance、应用层门禁、安全门禁已经通过。
3. `v2_adversarial_gate_status = passed`
   - 说明 forged receipt / forged proof / conflicting package / 多轮守恒这类对抗路径已经通过。
4. `consensus_gate_status = passed`
   - 说明当前 V2 共识分层门禁已经通过。
   - 当前门禁至少覆盖：
     - 共识核心状态机
     - announce / fetch / bootstrap 这类 sync 路径
     - restart 后 catch-up 路径
     - 静态网络下的 MVP 共识联调
     - 恢复 / restart 路径
   - 这条只表示“当前默认共识验证面已通过”，不自动等同于“TCP 正式证据已经形成”。
5. `v2_account_recovery_gate_status = passed`
   - 说明账户节点在共识端短时不可达后，能进入降级、恢复并重新稳定。
6. `stability_gate_status = passed`
   - 说明重启、抖动、burst 这类稳定性路径已经通过。
7. `official_testnet_gate_status = passed`
   - 说明正式测试网 profile 和连通性校验已经通过。
8. `external_trial_gate_status = passed`
   - 说明至少有一轮真实外部试用记录，且满足安装、建钱包、领水、转账、history/receipt 验证要求。
   - 单机伪远端这类 `single-host-rehearsal` 预演不算这条正式证据。
9. `release_report.risks` 为空
   - 说明当前候选版本没有未收口的发布阻断项。

## 共识 TCP 证据说明

`release_report` 和 `v2_readiness` 现在会额外带出共识 TCP 证据状态，用来区分：

- `consensus_gate` 已通过
- 但 TCP 多节点正式证据是否真的已经执行并形成

重点字段：

- `consensus_tcp_evidence_status`
- `consensus_formal_tcp_evidence_ready`

当前语义：

- 如果本机环境可以执行 TCP 共识套件，且相关套件通过，则可形成正式 TCP 共识证据。
- 如果当前环境因为端口绑定限制跳过了 TCP 共识套件，状态通常会显示为 `not_executed_bind_restricted`。
- 这种情况下不能把“共识 gate 已通过”解释成“真实 TCP 共识证据已经拿到”。
- 当前还需要额外注意一个执行层现象：
  - 某些 TCP pytest case 单独运行时，可能可以真实执行并通过
  - 但完整 `consensus_gate` 顺序执行时，同一机器仍可能在 TCP step 上返回 `bind_not_permitted`
  - readiness / release 的正式判断仍然以 `consensus_gate`、`release_report`、`v2_readiness` 这条证据链为准，而不是只看单个 TCP case 的单独结果

`v2_readiness.py` 现在会把这件事单独显示为 `consensus_tcp_evidence` 检查项，便于读报告时直接看出：

- 本地 / 静态网络共识验证已通过
- 还是 TCP 正式证据也已经形成

当前这条仍以信息披露为主，是否把它升级成阻断条件，仍以项目治理口径为准。

## 判断原则

如果上面任意一项没有满足，V2 仍然只能算：

- 默认研发路径
- 默认本地验证路径
- 默认内测路径

但还不能算“项目默认正式交付路径”。

## 推荐命令

先生成带完整证据的发布报告：

```bash
python3 scripts/release_report.py \
  --run-gates \
  --with-stability \
  --with-consensus \
  --with-v2-adversarial \
  --allow-bind-restricted-skip \
  --require-official-testnet \
  --official-config configs/ezchain.official-testnet.yaml \
  --official-check-connectivity \
  --external-trial-record doc/trials/official-testnet-YYYYMMDD-01.json
```

再生成 V2 默认化 readiness 判断：

```bash
python3 scripts/v2_readiness.py
```

如果走 RC 流程：

```bash
python3 scripts/release_candidate.py \
  --version v0.1.0-rc1 \
  --with-stability \
  --with-v2-adversarial \
  --require-official-testnet \
  --official-config configs/ezchain.official-testnet.yaml \
  --official-check-connectivity \
  --external-trial-record doc/trials/official-testnet-YYYYMMDD-01.json
```

说明：

- `release_candidate.py` 现在会自动把 `consensus_gate` 带进发布报告
- 所以 RC 流程里不需要再额外补一个 `--with-consensus`
- `release_report` 现在会把共识 core / sync / catch-up / recovery 状态，以及 TCP 正式证据状态写进顶层 summary
- 如果 TCP 共识套件因为当前环境限制未执行，报告会明确给出对应 risk，而不是把这部分信息藏在测试明细里

该流程会自动生成：

- `dist/release_report.json`
- `dist/v2_readiness.json`
- `dist/rc_manifest.json`

## 当前治理建议

在 `v2_readiness.py` 返回通过之前：

- V1 继续保持 freeze，不再新增功能。
- README / quickstart / 本地演示继续默认指向 V2。
- 对外沟通口径维持为：
  - `V2 是默认研发与验证路径`
  - `V2 是否成为默认正式交付路径，以 readiness gate 为准`
