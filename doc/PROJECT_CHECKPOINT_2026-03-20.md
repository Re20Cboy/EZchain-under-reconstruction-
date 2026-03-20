# EZchain Checkpoint (2026-03-20)

本检查点基于当前仓库可验证状态整理，重点关注 V2 默认化与项目落地收口。

## 总体判断

- 项目阶段：`V2 默认路径已成立 / MVP 内测可交付`
- 当前结论：
  - V2 已不再只是推荐路径，而是项目默认开发、验证、RC 判断路径
  - V1 保持 `legacy / freeze`
  - 从项目治理角度，`v2_readiness.py` 已可返回通过

## 本阶段完成项

1. V2 默认质量门已收口
- `release_gate`
- `release_report`
- `release_candidate`
- `rc_gate`

2. V2 对抗与鲁棒性验证已显著补强
- forged receipt / forged proof
- conflicting package
- mailbox 注入
- withheld receipt
- 长轮次混合攻击
- 上帝视角的诚实节点理论余额核对

3. 官方测试网证据链已收口
- `official-testnet` canonical profile 固化为 `configs/ezchain.official-testnet.yaml`
- 外部试用记录初始化、更新、校验链路已可用
- `external_trial_gate` 已能进入 `release_report -> v2_readiness -> rc_gate`

## 当前已验证状态

在以下条件下：

- 使用 `configs/ezchain.official-testnet.yaml`
- 提供通过的 external trial record
- 允许当前环境下的官方测试网连通性不可达 (`--official-allow-unreachable`)

已验证：

- `release_report` 通过
- `v2_readiness` 返回 `ready_for_v2_default = true`

## 当前剩余边界

下面这件事仍建议保留为运营侧确认动作，而不是被误解为已经完全结束：

- 在真实可达的官方测试网环境里，再跑一轮不带 `--official-allow-unreachable` 的正式验证

这不影响“项目默认路径已经切到 V2”的治理结论，但影响“运营侧是否完全确认当前候选环境可直接用于外部演练”的判断。

## 下一步建议

1. 更新对外文档与入口口径
- README
- 文档首页
- 发布清单

2. 在真实官方测试网环境再做一次可达性验证
- 不带 `--official-allow-unreachable`
- 作为运营侧最终确认

3. 保持 V1 freeze，不继续扩张旧路径
- 新功能继续默认进入 `EZ_V2`
