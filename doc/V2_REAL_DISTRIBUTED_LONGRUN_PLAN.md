# EZchain V2 Real Distributed Long-Run Test Plan

本计划用于把当前已经打通的多机交易闭环，推进成一套可连续执行、可留证据、可定位问题、可评估 checkpoint/恢复/稳定性收益的真实分布式测试路线。

它不是一次性 smoke。

目标是：

- 长期稳定运行 `EZchain-V2`
- 使用真实多节点部署和多轮交易驱动
- 系统性触发并验证 V2 关键机制
- 建立长期监控与证据收集
- 最终回答两个问题：
  - 功能是否完备
  - 像 checkpoint 这样的机制，是否真的提升效率、降低成本

## 1. 当前基线

基于最近一次真实试跑，当前已经确认：

- 真实两机分布式交易已经能跑通至少一笔确认交易
- 当前更稳定的网络拓扑是：
  - `Mac` 使用 Tailscale 地址
  - `ECS` 对外优先使用公网地址
- 当前有效验证者拓扑是 3 节点：
  - `consensus-1` on Mac
  - `consensus-2` on ECS
  - `consensus-3` on ECS
- `Mac` 账户节点连接 `consensus-1`
- `ECS` 账户节点连接本机 `consensus-2`

这意味着：

- 后续测试不应该再回到“只验证能不能启动”的阶段
- 默认起点应该是“真实分布式系统已经能确认交易”

## 2. 总体目标

后续测试分三层目标推进：

1. 功能完整性
   - 多轮交易
   - 双向收发
   - receipt / history / balance / pending 一致性
   - 账户恢复
   - 重启 catch-up
   - 共识继续出块
   - checkpoint 创建、持久化、使用

2. 稳定性与恢复性
   - 长时间运行
   - 单节点重启
   - 账户节点重启
   - 网络抖动
   - 交易 burst
   - 连续多轮提交

3. 效率与成本收益
   - checkpoint 是否降低验证成本
   - 恢复时间是否缩短
   - receipt / block sync 成本是否下降
   - 长跑中 CPU / 内存 / 网络开销是否可接受

## 3. 成功标准

计划不是“有输出就算过”，必须满足明确标准。

### 3.1 功能标准

- 连续 100 笔以上真实交易可确认
- 双向交易均可确认
- 任意时点检查：
  - 发送方 `available_balance + pending_balance` 合理
  - 接收方 `confirmed_balance` 与链上结果一致
  - `chain_height` 单调递增
- 账户重启后可恢复 receipt、history、balance
- 共识节点重启后可重新 catch up
- checkpoint 至少被真实创建并被真实验证路径使用一次

### 3.2 稳定性标准

- 24 小时长跑期间不出现系统性卡死
- 单节点重启后集群继续可用
- 单账户节点重启后不丢失确认交易状态
- burst 交易下无持续 pending 堆积

### 3.3 checkpoint 收益标准

必须至少拿到以下对比证据：

- 无 checkpoint 验证延迟
- 有 checkpoint 验证延迟
- checkpoint 使用率
- checkpoint 命中后的 witness / 验证工作量变化

如果拿不到这些指标，就不能声称 checkpoint “提升效率、降低成本”。

## 4. 分阶段计划

## Phase 0: 固化当前可运行拓扑

目标：

- 固定一套最少可运行的真实分布式拓扑
- 固定启动、停止、重启、状态检查命令
- 固定证据收集目录

执行项：

- 统一使用当前已验证的 3 验证者拓扑
- 固定链 ID、端口、地址
- 把运行日志保存在机器本地目录
- 每轮试跑产出单独记录文件

建议证据目录：

```text
doc/trials/distributed/
```

每轮记录建议至少包含：

- 拓扑
- 提交版本
- 启动命令
- 交易轮次
- 成功/失败笔数
- 余额快照
- 链高快照
- 异常日志摘要

## Phase 1: 多轮基础交易验证

目标：

- 证明系统不是“只能成功 1 笔”
- 覆盖双向交易和连续交易

建议轮次：

1. 单笔交易
   - `Mac -> ECS`
2. 单笔反向交易
   - `ECS -> Mac`
3. 10 笔顺序交易
4. 20 笔顺序交易
5. 双向交错交易

每轮都要检查：

- 两端余额
- 两端 `pending_bundle_count`
- 两端 `pending_incoming_transfer_count`
- 两端 `chain_height`
- 共识节点 `current_height`

最小通过条件：

- 无卡死 pending
- 无余额错账
- 无 receipt 丢失

## Phase 2: 长时间低速长跑

目标：

- 让系统在真实环境下持续运行
- 观察慢性问题，而不是只看 burst 时刻

建议时长：

- 2 小时
- 6 小时
- 24 小时

建议负载：

- 每 2 到 5 分钟发 1 笔交易
- 双向轮流发送
- 每小时至少一次状态快照

需要记录：

- 交易成功率
- 平均确认时延
- 失败类型分布
- 节点在线率
- 链高增长曲线

可复用现有脚本：

- [scripts/canary_monitor.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/scripts/canary_monitor.py)
- [scripts/stability_smoke.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/scripts/stability_smoke.py)

但当前这些脚本主要面向 service/metrics，本计划需要把分布式 V2 指标接进去。

## Phase 3: 恢复与重启验证

目标：

- 验证“长期运行时必然发生的重启/短断线”不会把系统打坏

场景：

1. 重启 `Mac` 账户节点
2. 重启 `ECS` 账户节点
3. 重启 `consensus-1`
4. 重启 `consensus-2`
5. 重启 `consensus-3`
6. 账户节点离线一段时间后恢复
7. 共识节点短时不可达后恢复

每个场景都要验证：

- 是否继续出块
- 是否能 catch up
- 是否丢 receipt
- 是否残留错误 pending
- 恢复后第一笔交易是否还能确认

重点证据：

- 恢复前后链高
- 恢复前后余额
- 恢复耗时
- 错误计数

## Phase 4: checkpoint 功能触发与正确性验证

目标：

- 不只是“checkpoint API 存在”
- 要验证 checkpoint 真在 V2 用户路径里起作用

当前代码里已经有相关基础：

- [EZ_V2/wallet.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZ_V2/wallet.py)
- [EZ_Test/v2_acceptance.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZ_Test/v2_acceptance.py)
- [EZ_Test/test_checkpoint.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZ_Test/test_checkpoint.py)

但当前不足是：

- 这些主要证明“checkpoint 可以创建/存储/基础使用”
- 还没把“真实分布式长跑中 checkpoint 的收益”做成系统监控

建议真实场景：

1. 连续多轮转移同一 Value 派生链
2. 在接收方创建 checkpoint
3. 后续再次验证同一条或相关派生链时，记录是否命中 checkpoint
4. 比较：
   - 命中 checkpoint 前后的验证时间
   - witness 深度
   - 数据大小

必须新增或收集的指标：

- `checkpoint_created_total`
- `checkpoint_used_total`
- `checkpoint_hit_rate`
- `verification_latency_ms_without_checkpoint`
- `verification_latency_ms_with_checkpoint`
- `verification_input_bytes_without_checkpoint`
- `verification_input_bytes_with_checkpoint`

如果没有这些对比指标，就只能说“checkpoint 功能存在”，不能说“checkpoint 有收益”。

## Phase 5: 交易 burst 与压力验证

目标：

- 让系统在一段时间内承受更密集交易
- 观察 pending、receipt、恢复、内存和时延变化

建议负载：

- 10 笔 burst
- 50 笔 burst
- 100 笔 burst

观察项：

- `pending_bundle_count` 是否持续积压
- receipt 回收是否正常
- 链高是否继续增长
- 节点是否出现持续超时
- burst 后系统是否能回到稳定状态

## Phase 6: 准生产连续试跑

目标：

- 建立一轮接近真实使用方式的 trial
- 为 readiness / release 提供更强证据

建议条件：

- 至少 24 小时
- 至少 100 笔确认交易
- 至少 1 次账户重启恢复
- 至少 1 次共识节点重启恢复
- 至少 1 次 checkpoint 命中验证
- 至少 1 份 canary/stability 报告

输出证据：

- 交易清单
- 指标报告
- 异常与恢复记录
- 结论与风险余项

## 5. 监控计划

长期试跑不能只看日志，必须有固定监控点。

## 5.1 当前可直接采集

当前已有的基础状态：

- 账户节点 `state.json`
  - `chain_cursor`
  - `receipt_count`
  - `pending_bundle_count`
  - `pending_incoming_transfer_count`
  - `last_sync_ok`
- service `/metrics`
  - 交易成功率
  - 平均确认延迟
  - 节点在线率
  - 错误码分布

可复用：

- [scripts/canary_monitor.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/scripts/canary_monitor.py)
- [scripts/metrics_probe.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/scripts/metrics_probe.py)

## 5.2 当前缺失但必须补充

为了回答“checkpoint 是否提升效率、降低成本”，当前至少还缺这些指标：

- checkpoint 命中率
- 每次验证耗时
- 每次验证输入大小
- proof / witness 深度
- receipt 拉取次数
- block fetch 次数
- catch-up 耗时
- 恢复后首笔确认时延

建议把这些指标加到：

- 账户节点状态
- service `/metrics`
- canary 报告输出

## 6. 推荐执行节奏

建议按周推进，不要一次铺太大。

### 第 1 周

- 固化拓扑
- 跑通 10 到 20 笔双向交易
- 固化重启流程
- 建立 trial 记录模板

### 第 2 周

- 跑 2 小时和 6 小时长跑
- 做账户/共识节点恢复验证
- 收集第一版长期运行指标

### 第 3 周

- 设计并补齐 checkpoint 收益指标
- 跑 checkpoint 触发型场景
- 比较命中前后验证成本

### 第 4 周

- 跑 24 小时准生产 trial
- 输出正式 trial 报告
- 对照 [doc/V2_DEFAULT_READINESS.md](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/doc/V2_DEFAULT_READINESS.md) 更新 readiness 判断

## 7. 需要继续补的实现项

这部分不是附录，而是计划能否成立的关键。

当前建议优先级：

### P0

- 把当前已验证的分布式拓扑固化成脚本化 profile
- 自动化多轮交易驱动脚本
- 自动化状态快照采集

### P1

- checkpoint 命中/收益指标
- 恢复耗时指标
- 长跑报告聚合脚本

### P2

- 更强的网络扰动模拟
- 更细的成本估计模型

## 8. 下一步实际推进建议

从当前状态出发，最该先做的不是再改协议，而是：

1. 固定当前可运行分布式拓扑
2. 写一个“多轮交易 + 周期状态采样”的分布式试跑脚本
3. 先跑一轮 20 笔双向交易
4. 再跑一轮 2 小时低速长跑
5. 在此基础上补 checkpoint 监控指标

也就是说，后续推进顺序应当是：

- `可重复试跑`
- `持续观察`
- `触发 checkpoint`
- `量化收益`

而不是直接跳到“默认认为 checkpoint 已经证明有效”。

