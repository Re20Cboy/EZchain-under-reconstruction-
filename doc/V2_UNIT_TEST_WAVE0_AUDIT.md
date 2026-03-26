# EZchain-V2 第 0 波测试口径审计

本文件对应 `doc/V2_UNIT_TEST_ADVANCEMENT_PLAN.md` 的第 0 波。

目标不是补新测试，而是先判断现有 V2 测试文件到底在证明什么，以及它们是否适合作为后续第 1 波和第 2 波的可信基础。

本轮审计最小设计依据：

- `EZchain-V2-design/EZchain-V2-protocol-draft.md`
- `EZchain-V2-design/EZchain-V2-consensus-mvp-spec.md`
- `EZchain-V2-design/EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-design/EZchain-V2-node-role-and-app-boundary.md`
- `AGENTS.md`

分类标签沿用推进计划：

- `aligned`
- `temporary divergence`
- `drift`
- `unclear`

`next action` 沿用推进计划：

- `keep`
- `rewrite`
- `split`
- `defer`

## 审计总表

| file | 主要想证明什么 | 当前更接近在证明什么 | classification | next action | 备注 |
| --- | --- | --- | --- | --- | --- |
| `EZ_Test/test_ez_v2_protocol.py` | 协议对象、receipt/prev_ref、递归 witness、checkpoint、validator 边界 | 设计语义与当前实现混合；单文件跨 `chain + validator + wallet` 三层 | `unclear` | `split` | 适合作为语义种子，但不适合作为最终 focused 协议测试承载体 |
| `EZ_Test/test_ez_v2_wallet_storage.py` | 钱包 pending、receipt 应用、重启恢复、prev_ref 连续性、sidecar 生命周期 | 大部分是设计要求，但也混入了钱包内部存储实现细节 | `temporary divergence` | `split` | 可保留现有回归价值，但应拆出 `storage_restart`、`receipts`、`checkpoint` focused tests |
| `EZ_Test/test_ez_v2_runtime.py` | runtime 驱动 wallet 收据恢复、离线恢复、transfer delivery、负向收据校验 | 主要是在证明当前 runtime + wallet 协作行为 | `temporary divergence` | `split` | 需要把“runtime owning boundary”与“wallet 自身语义”拆开 |
| `EZ_Test/test_ez_v2_network.py` | 静态网络、TCP 网络、MVP 共识、auto round、window batching、timeout、sync、catch-up、restart | 大量在证明当前宿主脚本化行为，且一个文件承担过多职责 | `drift` | `rewrite` | 这是当前最需要重写和拆分的测试文件 |
| `EZ_Test/test_ez_v2_consensus_core.py` | vote/QC/lock/timeout/TC 等核心状态机语义 | 主要在证明共识核心设计语义 | `aligned` | `keep` | 仍需后续补 proposal/QC 合法性更细负向测试 |
| `EZ_Test/test_ez_v2_consensus_pacemaker.py` | round 推进、timeout backoff、QC/TC 跳转 | 设计语义 | `aligned` | `keep` | focused 且边界清楚 |
| `EZ_Test/test_ez_v2_consensus_runner.py` | 单轮 commit helper 与 timeout helper 的连线正确性 | 当前实现辅助路径，不是完整规范行为 | `temporary divergence` | `split` | 适合保留为 helper 回归，不应被当成共识语义主证据 |
| `EZ_Test/test_ez_v2_consensus_sortition.py` | proposer claim 选择与验证 | 当前过渡态“签名式 proposer claim”接口 | `temporary divergence` | `keep` | 与 spec 一致地属于过渡实现，不可当成正式 VRF 已完成证据 |
| `EZ_Test/test_ez_v2_consensus_validator_set.py` | validator set 排序、去重、法定人数 | 设计语义 | `aligned` | `keep` | focused 且与许可型 validator set 设计一致 |
| `EZ_Test/test_ez_v2_consensus_store.py` | QC/lock/pacemaker/timeout 持久化恢复 | 设计语义 | `aligned` | `keep` | focused 且直接对应 restart/persistence 语义 |
| `EZ_Test/test_ez_v2_consensus_sync.py` | block announce / fetch / bootstrap 的同步与防伪边界 | 网络同步设计语义，但与 `test_ez_v2_network.py` 明显重叠 | `temporary divergence` | `split` | 可作为 `network sync` 子文件保留，但要与大而全网络测试去重 |
| `EZ_Test/test_ez_v2_consensus_catchup.py` | 账户恢复、共识 follower catch-up、restart 后追平 | 设计语义和集成路径混合 | `temporary divergence` | `split` | 应保留 catch-up 主题，但拆成 account recovery / follower catch-up 两个 focused 组 |
| `EZ_Test/test_ez_v2_consensus_tcp_catchup.py` | TCP 下 timeout+restart+catch-up | 真实传输集成行为 | `temporary divergence` | `split` | 有现实价值，但不能与静态网络、MVP 共识、catch-up 全揉在一起做主证据 |

## 逐项审计记录

### `EZ_Test/test_ez_v2_protocol.py`

它想证明：

- `Bundle / Receipt / prev_ref` 的基础协议关系
- 递归 `WitnessV2` 与 checkpoint anchor 可被 validator 接受
- 一些钱包 acquisition 边界和 tamper fail 行为

当前问题：

- 单文件跨了协议对象、链状态、validator、wallet 四种职责
- 某些断言在证明设计语义，某些断言在证明当前 wallet/chain 实现如何配合
- 如果以后 wallet 内部结构调整，这个文件会一起摇晃，导致我们分不清究竟是协议 drift 还是实现重构

判断：

- 不是错误测试
- 但不够 focused，且“文件通过”不能自动推出“协议层已证明”

结论：

- `classification: unclear`
- `next action: split`

### `EZ_Test/test_ez_v2_wallet_storage.py`

它想证明：

- pending bundle 持久化与重启恢复
- receipt 应用后的记录状态变化
- `prev_ref` 连续性破坏时拒收
- rollback / clear pending / sidecar GC

当前问题：

- 它一半在测钱包设计语义，一半在测 `LocalWalletDB` 组织方式
- 适合作为回归文件，但不适合作为“存储语义已经被直接证明”的唯一依据

结论：

- `classification: temporary divergence`
- `next action: split`

建议拆向：

- `test_ez_v2_storage_restart.py`
- `test_ez_v2_receipts.py`
- `test_ez_v2_checkpoint_core.py`

### `EZ_Test/test_ez_v2_runtime.py`

它想证明：

- runtime 如何驱动 bundle 提交、receipt 应用、离线 sender 恢复
- receipt missing 到 recovered 的状态切换
- transfer package 投递后接收方可再花费
- forged receipt / tampered proof 会被拒绝

当前问题：

- 这是典型的“小集成测试”，不是纯单元测试
- 它在证明 `runtime + wallet + chain` 的协作结果，而不是单独证明 owning boundary
- 目前文件通过，更像在说明“当前运行闭环能走通”，不是“runtime 边界已经完全清楚”

结论：

- `classification: temporary divergence`
- `next action: split`

### `EZ_Test/test_ez_v2_network.py`

它想证明：

- 账户提交
- 静态 peers
- TCP transport
- MVP proposer / timeout / restart
- auto round
- snapshot window batching
- block announce / bootstrap / catch-up
- follower late join / cluster recovery

当前问题：

- 单文件承载了过多主题，已经不是 focused 测试文件
- 其中部分断言在证明设计语义，部分断言只是当前宿主脚本行为，部分断言属于现实分布式 smoke
- 文件中存在“看到 commit 了就当语义正确”的风险，尤其是 auto round / proposer 选择 / batch 行为
- 它与 `test_ez_v2_consensus_sync.py`、`test_ez_v2_consensus_catchup.py`、`test_ez_v2_consensus_tcp_catchup.py` 有明显职责重叠

为什么判为 `drift`：

- 这类文件一旦长期作为主证据，会把“脚本能跑通”误当成“协议语义已证明”
- 这正是推进计划试图纠正的测试口径问题

结论：

- `classification: drift`
- `next action: rewrite`

### `EZ_Test/test_ez_v2_consensus_core.py`

它想证明：

- local vote conflict
- precommit QC 锁定
- commit QC 决议
- locked QC 对低 justify 分支的拒绝
- timeout vote / TC / round 推进

判断：

- 主题单一
- 断言目标清楚
- 大部分直接映射到 `consensus-mvp-spec`

结论：

- `classification: aligned`
- `next action: keep`

剩余缺口：

- proposal / vote / QC 的更细非法输入组合
- height / round / validator_set_hash 错配负向测试

### `EZ_Test/test_ez_v2_consensus_pacemaker.py`

判断：

- focused
- 纯状态机边界
- 与 spec 一致

结论：

- `classification: aligned`
- `next action: keep`

### `EZ_Test/test_ez_v2_consensus_runner.py`

它想证明：

- helper 可以把一轮 commit 或 timeout round 驱动完

当前问题：

- 它更像测试辅助器本身，而不是完整共识规范
- 如果把它当作主证据，会高估“单轮驱动 helper”对真实网络和 snapshot window 语义的证明能力

结论：

- `classification: temporary divergence`
- `next action: split`

### `EZ_Test/test_ez_v2_consensus_sortition.py`

它想证明：

- proposer claim 的选择和验证接口
- 错 key、篡改 output 时拒绝

当前问题：

- 当前实现是“签名式 proposer claim”过渡态
- 这符合 spec 中写明的过渡边界，但不能把它包装成正式 VRF 已完成

结论：

- `classification: temporary divergence`
- `next action: keep`

说明：

- 这里的 `keep` 不代表它是最终形式
- 它只是当前过渡实现的正确测试，不应被过度外推

### `EZ_Test/test_ez_v2_consensus_validator_set.py`

判断：

- focused
- 直接对应许可型 validator set 设计
- 结论清楚

结论：

- `classification: aligned`
- `next action: keep`

### `EZ_Test/test_ez_v2_consensus_store.py`

判断：

- 直接覆盖 restart / persistence
- 与第 1 波要求一致
- 主题单一

结论：

- `classification: aligned`
- `next action: keep`

### `EZ_Test/test_ez_v2_consensus_sync.py`

它想证明：

- block announce / fetch / bootstrap 的同步与防伪语义

当前问题：

- 文件主题本身是合理的
- 但部分内容在 `test_ez_v2_network.py` 中已有近似重复

结论：

- `classification: temporary divergence`
- `next action: split`

### `EZ_Test/test_ez_v2_consensus_catchup.py`

它想证明：

- account restart 后恢复 pending receipts 与缺失 block
- follower 共识节点重启后追平再继续参与后续路径

当前问题：

- 属于正确主题，但还是“小集成 + 现实场景”混合
- 账户恢复与 consensus follower catch-up 应分开建 focused 组

结论：

- `classification: temporary divergence`
- `next action: split`

### `EZ_Test/test_ez_v2_consensus_tcp_catchup.py`

它想证明：

- TCP 现实网络下 timeout / restart / catch-up

当前问题：

- 测的是现实运行闭环，很有价值
- 但不是单元语义主证据，且和大网络测试的职责边界仍不够清晰

结论：

- `classification: temporary divergence`
- `next action: split`

## 必须重写的测试文件名单

按第 0 波退出标准，当前至少应把下面文件列入“必须重写或强拆”名单：

- `EZ_Test/test_ez_v2_network.py`

下面文件列入“必须拆分”名单：

- `EZ_Test/test_ez_v2_protocol.py`
- `EZ_Test/test_ez_v2_wallet_storage.py`
- `EZ_Test/test_ez_v2_runtime.py`
- `EZ_Test/test_ez_v2_consensus_runner.py`
- `EZ_Test/test_ez_v2_consensus_sync.py`
- `EZ_Test/test_ez_v2_consensus_catchup.py`
- `EZ_Test/test_ez_v2_consensus_tcp_catchup.py`

## 第 0 波结论

当前已经可以回答推进计划要求的核心问题：

- 不再存在“完全不知道这个测试文件在验证什么”的目标文件
- 当前最危险的口径问题集中在 `test_ez_v2_network.py`
- 共识核心小文件整体质量明显高于网络/宿主混合大文件
- 第 1 波开始前，应优先从 `protocol / wallet_storage / runtime / network` 这四个大文件做拆分和重组

## 建议的下一步顺序

1. 先处理 `EZ_Test/test_ez_v2_network.py`，把它拆成：
   - `network submit / proposer forwarding`
   - `network sync`
   - `network catch-up`
   - `tcp transport smoke`
   - `mvp timeout / restart`
2. 再拆 `EZ_Test/test_ez_v2_protocol.py`，把协议对象、validator、wallet acquisition 分离。
3. 再拆 `EZ_Test/test_ez_v2_wallet_storage.py` 与 `EZ_Test/test_ez_v2_runtime.py`。
4. 拆完后再继续第 1 波 focused tests 扩展。
