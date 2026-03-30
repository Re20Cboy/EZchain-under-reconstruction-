# EZchain-V2 优化清单

本文件列出四项在当前架构约束（共识节点不追踪 Value、固定验证者集、半同步网络）下可实施的优化方案。前 3 项聚焦共识层；第 4 项聚焦 checkpoint / witness 存储语义，用于在不引入额外 sender↔recipient 往返的前提下，避免旧 owner 重收 Value 后出现“可验证但不可再流转”的死值风险。每项优化均为独立改进，不依赖其他项，可按优先级分批落地。

## 优化 1：Receipt 索引广播（替代逐一推送）

### 现状

当前设计中，块经 CommitQC 确认后，共识节点主动向每个 sender 逐一推送完整 Receipt（含 SMT 证明）。若块内包含 k 个 sender，则需 k 次独立推送。

### 问题

- 共识节点推送负载 O(k)/块，sender 数量多时带宽和连接管理压力大
- 轻量用户（移动端）被迫接收与自己无关的网络流量
- 推送失败后的重试逻辑增加共识节点复杂度

### 方案

将 Receipt 分发从"逐一推送"改为"索引广播 + 按需拉取"：

1. **广播 ReceiptMerkleRoot**：块确认后，共识节点广播一条轻量消息，仅包含 `block_hash + receipt_merkle_root`，`receipt_merkle_root = MerkleRoot(receipts_sorted_by_addr_key)`
2. **用户按需拉取**：用户收到广播后，检查自己是否在该块的 diff 中（本地比对 addr_key），如果是，向共识节点发送 `receipt_req` 拉取自己的 Receipt
3. 拉取响应中附带 Merkle proof，用户可验证 Receipt 确实在 `receipt_merkle_root` 中

### 收益

| 维度 | 变化 |
|------|------|
| 共识节点推送 | O(k) 主动推送 → O(1) 广播 + 按需响应 |
| 用户带宽 | 仅接收自己相关的 Receipt |
| 失败模型 | 推送失败 → 拉取超时，更简单可重试 |

### 代价

- 用户多一次 RTT（广播→请求→Receipt），可通过流水线化掩盖（块 N 确认后立即预请求块 N+1 的 diff 检查）
- 共识节点需维护 Receipt Merkle Tree（每块一棵，用后可丢弃）
- 需新增消息类型：`receipt_index_broadcast`

### 影响范围

- `networking.py`：新增消息类型
- `network_host.py`：Receipt 分发逻辑从推送改为广播+响应
- `chain.py`：`ReceiptCache` 增加 Merkle 索引能力
- `wallet.py`：拉取逻辑替代被动接收

---

## 优化 2：BLS 签名聚合（替代 QC 中的独立签名列表）

### 现状

当前 QC（Quorum Certificate）包含 2f+1 个独立 secp256k1 签名。以 f=2、n=7 为例，每个 QC ≈ 7 × 65 = 455 字节。验证者集合扩大后 QC 体积线性增长。

### 问题

- QC 体积 O(n)，随验证者数量线性增长
- 块头中 `justify_qc` 占比随 n 增大
- 共识投票消息（`consensus_vote`）的网络开销大

### 方案

用 BLS12-381 聚合签名替代 secp256k1 独立签名列表：

1. **密钥扩展**：每个验证者新增一个 BLS 密钥对（保留现有 secp256k1 密钥用于其他签名场景）
2. **投票签名**：验证者用 BLS 私钥对 vote_hash 签名
3. **QC 组装**：收集到 2f+1 个 BLS 签名后，聚合为单个签名 `agg_sig`，QC 结构变为 `(agg_sig, bitmap)` — 固定约 48 字节 + 位图
4. **QC 验证**：用位图对应的公钥列表 + agg_sig 做批量验证

### 收益

| 维度 | 变化 |
|------|------|
| QC 体积 | O(n × 65B) → O(48B + n/8)，约 10x 缩减 |
| 块头 justify_qc | 显著缩小 |
| 共识消息带宽 | vote 消息可聚合转发 |

### 代价

- BLS 签名验证比 secp256k1 慢约 10x，但只在组装/验证 QC 时各做一次，非热路径
- 每个验证者需管理两套密钥（secp256k1 + BLS），`ConsensusGenesisConfig` 需扩展
- 引入 BLS12-381 库依赖（如 `py_ecc` 或 `blst`）
- 聚合签名不可逐个提取原始签名，调试时需保留原始投票日志

### 影响范围

- `consensus/types.py`：QC 结构调整
- `consensus/qc.py`：VoteCollector 使用聚合逻辑
- `consensus/core.py`：QC 验证使用 BLS 批量验证
- `consensus/sortition.py`：可能仍保留 secp256k1（VRF 用途不同）
- `crypto.py`：新增 BLS 密钥生成、签名、聚合、验证接口
- `ConsensusGenesisConfig`：新增 BLS 公钥列表

---

## 优化 3：流水线化共识（Pipelined / Chained HotStuff）

### 现状

当前采用严格的 3-phase 非流水线共识：每个块必须完成 PREPARE → PRECOMMIT → COMMIT 三轮投票后才能提议下一个块。吞吐 = 1 块 / 3 × RTT。

### 问题

- 延迟和吞吐被 3 轮串行投票严重限制
- 验证者集合空闲时间长（等待前一个块走完三阶段）
- 网络带宽利用率低

### 方案

采用 Chained HotStuff 模式，将三个阶段重叠在连续的块上：

```
Round R:   Leader proposes Block H   → validators sign PREPARE (which is PRECOMMIT for H-1)
Round R+1: Leader proposes Block H+1 → validators sign PREPARE (which is COMMIT for H-1, PRECOMMIT for H)
Round R+2: Leader proposes Block H+2 → validators sign PREPARE (which finalizes H-1, COMMIT for H, PRECOMMIT for H+1)
```

核心变化：
1. **合并阶段**：PREPARE 投票同时充当对前一个块的 PRECOMMIT，PRECOMMIT 投票同时充当对前一个块的 COMMIT
2. ** chained QC**：每个块的 proposal 携带前一个块的 QC，形成 QC 链
3. **确认规则**：一个块在收到其后面第二个块的 QC 时被视为 finalized（即 3-chain 规则）
4. **Leader 轮换**：每个 round 由 VRF 选出不同的 leader

### 收益

| 维度 | 变化 |
|------|------|
| 稳态吞吐 | 1 块 / 3×RTT → 1 块 / 1×RTT（3x 提升） |
| 确认延迟 | 不变（仍需等待 3 个后续块确认） |
| 带宽利用率 | 大幅提高（每轮都有有效工作） |

### 代价

- 实现复杂度显著增加：需处理 chained QC 连续性、多块并行的 pacemaker 状态
- 安全性论证更复杂：需仔细证明 chained 模式下 3-chain 确认规则的 safety 和 liveness
- 回滚逻辑更复杂：当 chain 出现分叉时，需正确处理多个未确认块的丢弃
- 测试复杂度增加：需覆盖流水线填充、稳态、分叉恢复等更多场景

### 影响范围

- `consensus/core.py`：Safety 规则需适配 chained 模式（locked_qc 语义变化）
- `consensus/pacemaker.py`：Pacemaker 需跟踪多个并行的 round/phase
- `consensus/types.py`：Proposal 结构可能需携带 chained QC
- `consensus/runner.py`：驱动逻辑需支持流水线模式
- `chain.py`：块构建需与流水线节奏协调
- 这是对共识模块的**重写级别**改动，建议作为独立版本（如 V2.1）实施

---

## 优化 4：本地 Witness 重水合与保守 Sidecar 保活

### 现状

当前 V2 的 checkpoint 裁剪策略已经收口到 `exact-range only`：

- sender 只会在“recipient 就是该 Value 的旧 owner，且区间完全一致”时，把 prior witness 裁到 `CheckpointAnchor`
- recipient 收到这种裁剪包后，如果本地存在匹配 checkpoint，对应 wallet 会把 `CheckpointAnchor` 重新水合为本地完整 prior witness
- sidecar GC 重新计数时，会扫描所有本地 `value_records` 的 witness，包括 `ARCHIVED` 记录

### 问题

协议草案里的 `PL-001` 指出一个潜在风险：

- 旧 owner 把 Value 转出后，只保留 checkpoint，不再保留 checkpoint 之前的完整 witness / sidecar
- 当该 Value 以后被裁剪返回给旧 owner 时，旧 owner 虽能验证接受，但若要再转给一个不信任该 checkpoint 的第三方，就可能无法重建全量 witness
- 最坏情况下，Value 会变成“当前 owner 自己能认，但无法继续正常流转”的死值

### 方案

保持当前实现采用的“保守存储 + 本地重水合”策略，不急于引入额外协议交互：

1. **ARCHIVED 记录继续保留完整 witness**：Value 即使已转出，对应 `LocalValueRecord` 仍保存完整 `witness_v2`，不退化成纯 checkpoint 摘要
2. **sidecar GC 以 witness 可达性为准**：GC 重算引用时扫描全部 `value_records`，包括 `ARCHIVED` 记录；只要某段历史仍被本地 witness 引用，其 sidecar 就不能删
3. **旧 owner 收包后立即本地重水合**：若接收到的 witness 含 `CheckpointAnchor`，且本地能匹配到对应 checkpoint 与完整历史，则把 anchor 替换回本地完整 prior witness，再写入新 record
4. **对新第三方仍回退发完整 witness**：只有 exact-range 命中且 recipient 确实是旧 owner 时才裁剪；若下游第三方不信该 checkpoint，则 sender 直接发送完整 prior witness，而不是额外做 checkpoint 协商

### 收益

| 维度 | 变化 |
|------|------|
| 死值风险 | 旧 owner re-receive 后仍可继续向不信 checkpoint 的第三方转账 |
| 协议复杂度 | 无需立刻引入 `WitnessCompletionReq/Resp` |
| 网络成本 | 保持“sender 本地决定是否裁剪”，不新增发送前探测往返 |
| 故障模型 | 从“收回后可能不可再流转”变成“仅增加本地存储占用” |

### 代价

- 本地磁盘占用更保守：`ARCHIVED` 记录不会立刻瘦身，旧 witness / sidecar 保留时间更长
- sidecar GC 节省空间的收益被部分推迟，特别是高流转账户会累积更多历史对象
- 这更像“用存储换协议简单性”的临时稳妥路径，不一定是最终长期形态
- 若未来要做更激进的 witness / sidecar 瘦身，仍需要单独设计 `WitnessCompletionReq/Resp` 或等价恢复协议

### 影响范围

- `wallet.py`：`CheckpointAnchor` 的本地匹配、重水合、以及按 recipient 精确裁剪逻辑
- `storage.py`：sidecar refcount 重算与 GC 需继续以 witness 可达性为准，而不是只看活跃值
- `runtime_v2.py` / `localnet.py`：接收路径需保持“先验证、再重水合、再落盘”的语义
- `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py`
- `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint_recovery.py`

### 适用边界

- 当前 MVP 仍只支持 `exact-range checkpoint`
- `split / partial overlap return` 不做 checkpoint 复用，继续回退为完整 prior witness
- 该方案的本质是“保守保活”，不是 partial checkpoint 语义扩展
- 如果未来要把 archived witness 从本地裁掉，这一方案必须先升级成显式的 witness completion 协议

---

## 实施优先级建议

| 优先级 | 优化项 | 理由 |
|--------|--------|------|
| **P0** | Receipt 索引广播 | 改动范围可控，直接缓解共识节点推送压力，移动端友好 |
| P1 | BLS 签名聚合 | 引入新密码学依赖，但 QC 缩减效果明确，网络层收益大 |
| P2 | Pipelined HotStuff | 收益最大但实现复杂度最高，属于共识模块重写，建议在 MVP 稳定后单独规划 |
| P0 | 本地 Witness 重水合与保守 Sidecar 保活 | 不改协议消息即可消除 `PL-001` 类死值风险，适合作为当前默认存储语义继续明确和固化 |

前四项优化相互独立，可分别实施。两个 P0 都可以在不改变共识安全模型的前提下先行落地：前者优化 Receipt 分发，后者用更保守的本地存储语义换取 witness 完整性与后续可流转性。

---

# 第二批优化方案（基于最新研究调研）

以下优化基于 2024–2026 年区块链共识、无状态客户端、证明压缩等方向的最新学术研究和工程实践，结合 EZchain-V2 的架构约束筛选而来。核心筛选标准：

- **不违反"共识节点不追踪 Value"的原则**
- **不引入 ZK/Verkle 作为 MVP 依赖**（但 Verkle 作为远期选项列入）
- **对现有协议消息格式无破坏性变更**
- **对移动端用户有明确收益**

参考来源见文末。

---

## 优化 5：SMT Multi-Proof 批量压缩 Receipt 证明

> **通俗解释——拼车送 Receipt**
>
> 一个块里有 100 个 sender，就像 100 个人要去同一个目的地。现在每人各自开车（独立生成 SMT 证明），每人 ~8 KB。问题是这 100 条路线靠近终点（树根）的路段几乎完全重叠，重复走了 100 遍。优化后改成拼车——合并成一张共享地图，重叠路段只记录一次，每人只拿自己的出口索引。100 个 sender 从 ~800 KB 降到 ~25 KB，压缩 30 倍。

### 现状

当前块内有 k 个 sender 时，共识节点为每个 sender 独立生成一棵 SMT inclusion proof。256-bit 深度的 SMT 每条 proof 包含 256 个兄弟节点哈希（32 字节/个），单条 proof ≈ 8 KB。k 个 sender 的 Receipt 总证明体积 = 8k KB。

### 问题

- **证明体积随 sender 数线性增长**：100 个 sender → ~800 KB 仅证明部分
- **证明之间有大量重复**：同一块内所有 proof 走的是同一棵 SMT，它们在靠近 root 的高层兄弟节点大量重叠，但独立 proof 模式下这些重叠节点被重复存储和传输
- 移动端用户即使在优化 1 的按需拉取模式下，单个 Receipt 的证明仍有 ~8 KB

### 方案

在 Receipt 生成阶段，使用 **Merkle Multi-Proof**（多证明合并）技术，将同一块内所有 k 个 sender 的 SMT proof 合并为单一数据结构：

1. **合并证明路径**：遍历所有 k 个目标叶子，收集所有必需的兄弟节点，构建最小覆盖集
2. **共享内部节点**：靠近 root 的高层兄弟节点只出现一次，不按 per-sender 重复
3. **per-sender 索引**：为每个 sender 附带一个短索引，指示其在合并证明中的路径位置

数学原理：k 个叶子的 Multi-Proof 大小为 O(k + log n × log k)，而 k 条独立 proof 为 O(k × log n)。对于 n = 2²⁵⁶（当前 SMT 深度），log n = 256。

```
k 条独立 proof:    256 × k 个哈希
Multi-Proof:       k + 256 × ceil(log2(k)) 个哈希
节省比例:          约 (256k - k - 256×log2(k)) / 256k ≈ 1 - 1/256 - log2(k)/k
```

| k (sender 数) | 独立 proof 总大小 | Multi-Proof 大小 | 压缩比 |
|---|---|---|---|
| 10 | ~80 KB | ~5.6 KB | 14x |
| 100 | ~800 KB | ~25 KB | 32x |
| 1000 | ~8 MB | ~42 KB | **190x** |

### 收益

| 维度 | 变化 |
|------|------|
| 证明总生成量 | O(k × 256) → O(k + 256 × log k) |
| Receipt 广播/存储体积 | 数量级缩减，直接降低带宽和磁盘 |
| 移动端 | 单个 Receipt 的 proof 部分从 ~8 KB 降至共享后的均摊值 |
| 共识节点 CPU | Multi-Proof 生成可复用遍历中间结果，避免重复计算 |

### 代价

- 实现复杂度增加：需要实现 Multi-Proof 构建器和对应的验证器
- Receipt 数据结构需调整：从单条 proof 变为 multi-proof 的一个切片
- 向后兼容：旧版本客户端需要升级才能解析新的 Receipt 格式
- 单个用户的均摊 proof 仍包含一些与自己无关的节点（但总量远小于独立 proof）

### 影响范围

- `smt.py`：新增 `build_multi_proof()` 和 `verify_multi_proof()` 接口
- `chain.py`：`build_block()` 中 Receipt 生成逻辑改用 multi-proof
- `types.py`：Receipt 结构可能需调整为引用块级 multi-proof + 偏移量
- `network_host.py`：Receipt 广播可改为"块级 multi-proof 一次广播 + 索引"
- `wallet.py`：Receipt 验证逻辑适配 multi-proof

### 参考文献

- [Merkle Multi-Proofs — 数学分析与精确界限](https://xn--2-umb.com/25/merkle-multi-proof/)
- [Efficient and Universal Merkle Tree Inclusion Proofs via OR Aggregation (MDPI 2024)](https://www.mdpi.com/2410-387X/8/3/28)

---

## 优化 6：HotStuff-2 两阶段共识（Pipelined 的轻量替代）

> **通俗解释——三审改两审**
>
> 现在一个块要过三关才能确认（PREPARE → PRECOMMIT → COMMIT），像三审终审制。优化后研究发现两审就够了（PREPARE → COMMIT），省掉中间那一轮，延迟降低 33%。跟之前提的"流水线化"的区别：流水线是盖高楼——楼上还没封顶就开始盖下一层，吞吐提升大但工程量巨大；两阶段是直接砍掉一个环节，简单直接。
>
> ⚠️ **安全性备注**：HotStuff-2 是 2025 年的学术论文成果，其两阶段 BFT 的安全性论证在学界尚未经过充分的同行评议和工程验证。**暂不作为主要优化项**，仅作为研究方向记录，待学术共识成熟后再评估落地可行性。

### 现状

当前采用经典 HotStuff 三阶段（PREPARE → PRECOMMIT → COMMIT），每确认一个块需要 3 轮投票消息。优化 3 提出的 Pipelined HotStuff 可将稳态吞吐提升 3x，但实现复杂度属于"共识模块重写级别"。

### 问题

- Pipelined HotStuff 是一步到位的方案，实现成本高、测试复杂
- 是否存在一个**中间步骤**，以更低的代价获得部分收益？

### 方案

采用 **HotStuff-2**（2024 年最新研究成果），将三阶段压缩为两阶段：

1. **两阶段设计**：仅保留 PREPARE 和 COMMIT（省略 PRECOMMIT），通过精巧的 locked_qc 语义保证 safety
2. **响应式超时**：超时时间与网络实际延迟挂钩（而非固定值），坏情况下回退到固定上限
3. **最优性证明**：HotStuff-2 是在"响应式 BFT"模型下 phase 数量的理论下界——不可能比两阶段更少

```
当前 3-phase:  PREPARE → PRECOMMIT → COMMIT   (3 RTT/块)
HotStuff-2:    PREPARE → COMMIT                (2 RTT/块)
Pipelined:     流水线填充后 1 RTT/块             (需重写)
```

### 收益

| 维度 | 变化 |
|------|------|
| 共识延迟 | 3 RTT → 2 RTT（33% 降低） |
| 实现复杂度 | 远低于 Pipelined，接近对当前 3-phase 的"删减"而非"重写" |
| 理论保证 | 已证明为响应式 BFT 的 phase 下界 |
| 与 Pipelined 的关系 | 可作为 Pipelined 的前置步骤：先 2-phase 稳定，再叠加流水线 |

### 代价

- 仍需修改共识核心逻辑（`ConsensusCore` 的 safety 规则）
- locked_qc 的语义从 PRECOMMITQC 驱动变为 COMMITQC 驱动，需重新审视 edge case
- 两阶段 BFT 的安全性论证需独立审计（虽然论文已证明，但工程实现需验证）
- 不如 Pipelined 的吞吐提升大（2x vs 3x 相对于当前），但代价远低

### 影响范围

- `consensus/core.py`：Safety 规则从 3-phase 改为 2-phase
- `consensus/pacemaker.py`：超时逻辑适配响应式模型
- `consensus/types.py`：Vote.phase 枚举从三值改为二值
- `consensus/qc.py`：QC 组装逻辑简化
- `consensus/runner.py`：驱动逻辑调整

### 参考文献

- [HotStuff-2: Optimal Two-Phase Responsive BFT (arXiv:2503.10292, March 2025)](https://arxiv.org/pdf/2503.10292)
- [Cheetah: Pipelined BFT Consensus Protocol with High Throughput and Low Latency (2025)](https://www.researchgate.net/publication/402466616_Cheetah_Pipelined_BFT_Consensus_Protocol_with_High_Throughput_and_Low_Latency)

---

## 优化 7：见证链公共前缀去重验证

> **通俗解释——简历只查一次**
>
> Alice 一次给 Bob 转 10 个 Value，每个 Value 的见证链都要追溯 Alice 的链上历史。而 10 个 Value 共享同一段历史（最近几个块的记录），现在却每个都从头查一遍——就像 HR 招同一个公司的 10 个人，把公司营业执照验了 10 次。优化后按人分组，公共历史只验一次、缓存结果，各自不同的部分再分别验。10 个 Value 从验证 50 次降到 8 次，省了将近一半。

### 现状

当 recipient 从同一 sender 接收多个 Value 时（例如一次 P2P 交付中包含多笔交易），每个 Value 的 WitnessV2 都包含一段 `confirmed_bundle_chain`，沿着 sender 的 `prev_ref` 链回溯。同一 sender 的多个 Value 在同一块的 ConfirmedBundleUnit 完全相同，且在相邻块的链段也高度重叠。

### 问题

当前验证是 **per-Value 串行** 的——即使 10 个 Value 来自同一 sender 且共享 90% 的 bundle chain，仍需独立验证 10 次，SMT proof 重复校验 10 次。移动端 CPU 浪费严重。

### 方案

在 `V2TransferValidator` 中实现 **前缀去重批量验证**：

1. **按 sender 分组**：将待验证的多个 TransferPackage 按 `current_owner_addr` 分组
2. **公共前缀识别**：对同一 sender 的所有 witness，提取 `confirmed_bundle_chain` 的公共前缀（通常是最近几个块的 ConfirmedBundleUnit）
3. **前缀只验一次**：公共前缀段的 SMT proof 和 prev_ref 连续性只验证一次，缓存结果
4. **后缀独立验证**：各 Value 在公共前缀之后的不同路径（不同 acquire_tx）独立验证

```
Value A witness: [Block 10] → [Block 11] → [Block 12] → [acquire_A at Block 13]
Value B witness: [Block 10] → [Block 11] → [Block 12] → [acquire_B at Block 13]
Value C witness: [Block 10] → [Block 11] → [Block 12] → [Block 13] → [acquire_C at Block 14]

公共前缀: [Block 10, 11, 12]  ← 只验 1 次（而非 3 次）
后缀: A/B 共享 Block 13（验 1 次共享 + 2 次独立 acquire）
      C 独享 Block 13→14（验 1 次）
总计: 4 + 1 + 2 + 1 = 8 次验证（而非 3 × 5 = 15 次，节省 47%）
```

### 收益

| 维度 | 变化 |
|------|------|
| 验证 CPU | 同 sender 多 Value 场景下 O(k × L) → O(L + k × δ)，L=链长，δ=后缀差 |
| 移动端 | 批量接收同一 sender 的多笔 Value 时，CPU 开关显著降低 |
| 正确性 | 不改变验证语义，只是避免重复工作 |
| 内存 | 缓存公共前缀的验证结果，O(L) 额外内存（可接受） |

### 代价

- 纯客户端优化，不影响协议/网络层
- 需改造 `V2TransferValidator.validate_transfer_package()` 接口，支持批量输入
- 调用方（`WalletAccountV2` / `V2Runtime`）需改为先按 sender 聚合再调用
- 公共前缀算法需处理 witness 链长度不一致的情况

### 影响范围

- `validator.py`：新增 `validate_transfer_batch()` 批量接口
- `wallet.py`：接收多 Value 时改为批量调用
- `runtime_v2.py`：编排批量验证逻辑

---

## 优化 8：SMT Proof Delta 增量更新（离线用户 Receipt 保鲜）

> **通俗解释——打补丁而不是重装**
>
> 用户手机关机 2 小时，错过了 50 个块，Receipt 里的证明过期了。现在要向共识节点下载一份全新完整证明（~8 KB），像手机系统坏了直接重刷整机。优化后，共识节点每次出块时顺便广播一个小"补丁"（只含这块改了哪些路径），用户在本地依次打 50 个补丁就能把旧证明更新到最新。补丁体积远小于完整证明，且不需要单独向共识节点请求。

### 现状

当用户离线错过块 H，其 Receipt 中的 SMT proof 对应的是块 H-1 的 state_root。用户上线后需要向共识节点请求最新 Receipt（`receipt_req`），共识节点需从当前 state tree 重新生成完整 SMT proof。

### 问题

- 共识节点为离线用户重新生成 proof 的成本 = O(log n)，如果大量用户同时上线（如区域性网络恢复），可能形成 proof 生成风暴
- 用户无法在本地对自己的旧 proof 做"保鲜"，只能请求全量替换

### 方案

借鉴 LVMT（USENIX OSDI '23）的常量时间证明更新思想，引入 **Proof Delta** 机制：

1. **块级 Proof Delta**：共识节点在应用块 H 时，记录所有被修改的叶子路径上的兄弟节点变更（即 SMT 从 state_root_H-1 到 state_root_H 的路径 diff）
2. **Delta 广播**：将 Proof Delta 作为 `block_announce` 的附带字段广播（或在优化 1 的索引广播中附带）
3. **本地保鲜**：用户收到 Delta 后，可以在本地更新自己的旧 SMT proof，无需向共识节点请求全量 proof
4. **Delta 链式叠加**：如果用户错过了多个块，可以连续应用多个 Delta，从旧 proof 演化到最新 proof

```
用户 Receipt 的 SMT proof 对应 state_root_H-1
块 H 修改了叶子 X（路径 P_X）
  → Proof Delta = {P_X 上的新兄弟节点}
用户本地更新：
  → 如果自己的叶子在 P_X 的影响范围内，应用 Delta 更新 proof
  → 否则 proof 不变（state_root 变了，但路径未受影响）
```

### 收益

| 维度 | 变化 |
|------|------|
| 离线恢复 | 用户可本地修补旧 proof，减少对共识节点的 `receipt_req` 请求 |
| 共识节点负载 | 批量上线场景下，proof 生成请求大幅减少 |
| 带宽 | Delta 体积远小于完整 proof（只含变更路径） |

### 代价

- 共识节点需在块应用时额外记录路径变更，增加 O(k × log n) 的内存/CPU 开销（k = 块内 diff entry 数）
- `block_announce` 消息体积增加（附带 Delta 数据）
- 需设计 Delta 的序列化格式和本地应用算法
- Delta 链式叠加在极端情况下可能引入累积误差，需设置校验点（每 N 个块发一次完整 state_root 供校验）

### 影响范围

- `smt.py`：新增 `compute_proof_delta()` 和 `apply_proof_delta()` 接口
- `chain.py`：`apply_block()` 时记录路径变更
- `networking.py`：`block_announce` 消息扩展
- `wallet.py`：Receipt 本地保鲜逻辑

### 参考文献

- [LVMT: An Efficient Authenticated Storage for Blockchain (USENIX OSDI '23, ACM Trans. Storage 2024)](https://dl.acm.org/doi/abs/10.1145/3664818)

---

## 优化 9：Verkle Tree 远期迁移（Proof 体积从 ~8 KB 降至 ~1 KB）

> **通俗解释——换一棵更矮的树**
>
> 现在用的是 256 层深的二叉树（SMT），证明一条数据在里面需要提供 256 个兄弟节点哈希，约 8 KB。Verkle Tree 改用更宽的树（每层 256 个分支而不是 2 个），256-bit 的 key 只需要 32 层就到底，配合多项式承诺（一种把一组数据"压缩"成一个数的数学技巧），证明只需 32 个承诺值 ≈ 1 KB。但代价大：需要新密码学库、不抗量子计算、是共识层硬分叉级别改动，留给未来。

### 现状

当前 SMT（256-bit 深度）的单条 inclusion proof 包含 256 个兄弟节点哈希，约 8 KB。这是所有 Receipt 和 witness 验证的基础开销。

### 问题

- 8 KB 的 proof 体积对移动端不友好（特别是多个 Value 的 P2P 交付场景）
- SMT proof 大小 O(log₂ n) = O(256) 哈希，不可再压缩
- 与 Verkle Tree 的 ~1 KB proof（基于 KZG 多项式承诺）相比有数量级差距

### 方案

将底层认证数据结构从 SMT 迁移为 Verkle Tree：

1. **Verkle Tree 原理**：用 Pedersen 向量承诺替代 Merkle 中间节点哈希。宽度为 w 的 Verkle Tree，proof 大小 = O(log_w n) 个承诺 + 开口，而非 O(log₂ n) 个哈希
2. **参数选择**：以宽度 w=256 为例，256-bit key space 的 Verkle Tree 深度仅为 32 层（256/8），proof 包含 32 个承诺开口 ≈ ~1 KB
3. **迁移路径**：在 V2 稳定后，将 `smt.py` 替换为 `verkle.py`，state_root 计算和 proof 生成/验证接口保持不变

### 收益

| 维度 | 变化 |
|------|------|
| 单条 proof 体积 | ~8 KB → ~1 KB（8x 缩减） |
| Receipt 体积 | 直接缩减 |
| Witness 验证数据量 | 每个 ConfirmedBundleUnit 的 SMT proof 缩减 |
| 移动端 | 网络和存储成本显著降低 |

### 代价

- **不后量子安全**：Verkle Tree 依赖 pairing-based 密码学（KZG 承诺），不抗量子计算
- **实现复杂度高**：需要引入椭圆曲线配对运算库
- **迁移影响面大**：`state_root` 和 `diff_root` 的计算方式完全改变，所有历史 proof 失效
- **共识硬分叉**：state_root 语义变化意味着需要协调升级

### 适用性判断

| 条件 | 评估 |
|------|------|
| MVP 阶段适用？ | **否**——工程成本过高，且引入非必要依赖 |
| V2.1/V2.2 阶段适用？ | **可能**——如果 proof 体积成为瓶颈，可作为专项迁移 |
| 前置条件 | 共识模块稳定 + 有明确的 proof 体积瓶颈数据 |
| 与其他优化的关系 | 与优化 5（Multi-Proof）互补：Verkle 降单 proof 大小，Multi-Proof 降多 proof 总量 |

### 影响范围

- `smt.py` → `verkle.py`：整棵认证树替换
- `types.py`：BlockHeaderV2.state_root 语义变化
- `chain.py`：state_root/diff_root 计算逻辑重写
- `validator.py`：proof 验证逻辑替换
- **共识硬分叉**：所有节点必须同步升级

### 参考文献

- [Benchmarking Verkle Trees and Binary Merkle Trees with SNARKs (arXiv 2504.14069, 2025)](https://arxiv.org/html/2504.14069v1)
- [Ethereum "The Verge" — Stateless Client Roadmap (Vitalik, 2024)](https://vitalik.eth.limo/general/2024/10/23/futures4.html)
- [EDRAX: A Cryptocurrency with Stateless Transaction Validation (IACR 2018/968)](https://eprint.iacr.org/2018/968.pdf)

---

## 优化 10：可选 Bundle `claim_set_hash` 承诺（不建议直接把全量 Value 塞进 state leaf）

### 动机

当前 V2 明确选择"不引入 `claim_set_hash`"，因此 recipient 在验证 Witness 时，必须扫描整个 `BundleSidecar`，检查目标 Value 有没有在当前 sender 历史中被提前花销。这在 witness 较长、bundle 较胖时，会成为用户侧的真实 CPU / 带宽热点。

### 原始设想

把 `state_root` 的叶子从当前更轻的账户头语义，扩展为带"该 bundle 包含的全部 Value 列表"的更胖叶子，让 recipient 先看 Value 列表，再决定是否拉取完整 bundle。

### 判断

这个方向抓住了真实痛点，但**不建议**按"把全量 Value 原样并入 `AccountLeaf`"落地。更合理的做法，是把它收敛为 **bundle 级的 `claim_set_hash` 承诺**：不把全量 Value 列表直接塞进叶子，但若要引入 `claim_set_hash`，它本身必须进入 `AccountLeaf`（或等价的、被 `state_root` 直接承诺的叶子字段），这样 recipient 才有链上信任锚点可验证。这里统一沿用协议草案中的 `claim_set_hash` 命名。

### 为什么不建议把全量 Value 直接扩张进 state leaf

- **链上信任锚点不能缺席**：如果要做 `claim_set_hash`，它必须进入 `AccountLeaf`（或其他等价的 `state_root` 承诺字段）；若只是链下旁带字段，recipient 没有任何链上锚点可核验，这个摘要就不具备安全意义
- **但不该把全量 Value 原样塞进去**：真正不建议的是把 bundle 里的全部 `ValueRange` 原样并入 `AccountLeaf`，这会把一个本应定长的状态叶子膨胀成内容叶子
- **热路径重复承诺**：区块 `DiffPackage` 已携带完整 `BundleSidecar`，follower 也会重算 `bundle_hash` 校验；若再把所有 Value 原样塞进叶子，相当于在共识热路径重复携带同一批 Value 数据
- **只能省负例，不能替代正例检查**：摘要即使命中目标 Value，recipient 仍必须拉取并扫描完整 bundle，去确认目标 tx 是否真实存在、是否唯一、是否发给正确 recipient，以及是否存在重复/相交花销
- **最坏情况下摘要接近 bundle 本体**：高碎片或多 tx bundle 下，`all Values` 列表本身就可能接近 sidecar 的主要体积，节省并不稳定
- **协议升级面过大**：leaf 编码、Receipt 重建语义、proof 绑定、兼容性和测试都要一起改，收益却主要集中在 recipient 的"负向过滤"场景

### 更合理的收敛方案

1. **保持 `AccountLeaf` 定长，但允许新增一个摘要字段**：不把原始 Value 列表直接并入 state leaf，而是在 `AccountLeaf` 中新增固定长度的 `claim_set_hash`
2. **`claim_set_hash` 必须可由 `BundleSidecar` 重算**：leader / follower 基于完整 sidecar 规范化编码全部 `ValueRange`，重算并验证 `claim_set_hash`，确认 proposer 没有伪造摘要
3. **Receipt 通过叶子证明把 `claim_set_hash` 绑定到链上**：recipient 验证 `account_state_proof` 时，重建出的 `AccountLeaf` 中必须包含该 `claim_set_hash`，这样它才是有链上信任锚点的负向过滤承诺
4. **摘要与完整 sidecar 分层使用**：sender 可先给 recipient 发 `Receipt + 已被链上叶子承诺的 claim_set_hash`；只有当 `claim_set_hash` 显示目标 Value 可能命中时，recipient 再请求或展开完整 `BundleSidecar`

### 收益

| 维度 | 变化 |
|------|------|
| recipient 负向过滤 | 历史 bundle 若与目标 Value 无交集，可跳过完整 sidecar 扫描 |
| 全局状态语义 | `state_root` 仍以账户头状态为主，只额外承诺一个固定长度 `claim_set_hash`，而不是整份交易内容 |
| 共识可验证性 | 不新增信任假设；`claim_set_hash` 仍可由完整 sidecar 重算 |
| 后续演进 | 与协议草案中"未来可选的 `claim_set_hash`"方向一致 |

### 代价

- 仍然需要新增一种规范化 `claim_set_hash` 编码和哈希规则，并扩展 `AccountLeaf` 语义
- 若 `claim_set_hash` 命中目标 Value，recipient 仍要取完整 bundle，不能省掉正例验证
- 需要额外的对象缓存或按需拉取流程，否则 `claim_set_hash` 与完整 sidecar 同时发送时收益有限
- 这是协议升级，不是代码级微调；消息格式、验证器和测试都要同步改

### 适用性判断

| 条件 | 评估 |
|------|------|
| 你原始提出的"全量 Value 直接进 state leaf" | **不建议** |
| 收敛为"在 `AccountLeaf` 中加入定长 `claim_set_hash`，而不是塞入全量 Value" | **可以作为 V2.x 候选研究项** |
| MVP / 当前默认路径是否应立即做 | **否** |
| 更适合的前置工作 | 先补齐真实 workload 下的 recipient 验证 CPU / 带宽剖面，再判断是否值得升级 |

### 影响范围

- `EZchain-V2-protocol-draft.md`：明确 `claim_set_hash` 的规范化语义，以及它如何进入 `AccountLeaf`
- `EZ_V2/types.py`：`AccountLeaf` / `BundleEnvelope` / `DiffEntry` / `ConfirmedBundleUnit` 的承诺字段扩展
- `EZ_V2/validator.py`：先做 `claim_set_hash` 负向过滤，再按需做完整 bundle 冲突检查
- `EZ_V2/chain.py`：leader / follower 从 sidecar 重算并验证 `claim_set_hash`
- `EZ_Test/`：补充"`claim_set_hash` 命中 / 未命中 / 伪造 / hit 后仍需 full bundle"的 focused tests

---

## 全部优化实施优先级总表

| 优先级 | 编号 | 优化项 | 核心收益 | 实现代价 |
|--------|------|--------|---------|---------|
| **P0** | 1 | Receipt 索引广播 | 共识推送 O(k)→O(1) | 中 |
| **P0** | 4 | Witness 重水合 + Sidecar 保活 | 消除死值风险 | 低 |
| **P0** | 5 | SMT Multi-Proof 批量压缩 | 证明体积 14–190x 缩减 | 中 |
| **P1** | 2 | BLS 签名聚合 | QC 体积 ~10x 缩减 | 中 |
| **观望** | 6 | HotStuff-2 两阶段 | 延迟 33% 降低（比 Pipelined 代价低得多） | 中 | **学术界安全性尚未定论，暂不作为主要优化项，仅作研究方向记录** |
| **P1** | 7 | 见证链公共前缀去重验证 | 同 sender 多 Value 验证 CPU 减半 | 低 |
| **观望** | 10 | Bundle Value 摘要承诺 | recipient 可先做负向过滤，减少历史 bundle 拉取与扫描 | 中高（协议升级） |
| P2 | 3 | Pipelined HotStuff | 吞吐 3x 提升 | 高 |
| P2 | 8 | SMT Proof Delta 增量更新 | 离线恢复减轻共识节点压力 | 中 |
| P3 | 9 | Verkle Tree 远期迁移 | 单 proof 8x 缩减 | 很高（硬分叉） |

---

## 参考文献汇总

### 共识层
- [HotStuff-2: Optimal Two-Phase Responsive BFT (arXiv, 2025)](https://arxiv.org/pdf/2503.10292)
- [Cheetah: Pipelined BFT (2025)](https://www.researchgate.net/publication/402466616_Cheetah_Pipelined_BFT_Consensus_Protocol_with_High_Throughput_and_Low_Latency)
- [Shoal++: High Throughput DAG BFT (2024)](https://arxiv.org/html/2405.20488v2)
- [Bullshark: DAG BFT Made Practical (2022)](https://arxiv.org/abs/2201.05677)

### 证明压缩与无状态客户端
- [Merkle Multi-Proofs 数学分析](https://xn--2-umb.com/25/merkle-multi-proof/)
- [Efficient Merkle Inclusion Proofs via OR Aggregation (MDPI 2024)](https://www.mdpi.com/2410-387X/8/3/28)
- [Reckle Trees: Updatable Merkle Batch Proofs (ACM CCS 2024)](https://dl.acm.org/doi/10.1145/3658644.3670354)
- [LVMT: Efficient Authenticated Storage (USENIX OSDI '23)](https://dl.acm.org/doi/abs/10.1145/3664818)
- [Benchmarking Verkle Trees vs Binary Merkle Trees with SNARKs (arXiv 2025)](https://arxiv.org/html/2504.14069v1)
- [EDRAX: Stateless Transaction Validation (IACR 2018/968)](https://eprint.iacr.org/2018/968.pdf)
- [CompactChain: Stateless UTXO via RSA Accumulators (arXiv)](https://arxiv.org/abs/2211.06735)

### 以太坊路线图
- [The Verge: Stateless Client Roadmap (Vitalik, 2024)](https://vitalik.eth.limo/general/2024/10/23/futures4.html)
- [Optimizing Sparse Merkle Trees (ethresear.ch)](https://ethresear.ch/t/optimizing-sparse-merkle-trees/3751)
