# V2 Capacity Assessment And Optimization Plan

本文件回答一个落地前的关键问题：

> EZchain V2 在真实分布式 P2P 环境长期运行后，共识节点和用户节点的存储、计算、通信成本，是否仍能被端侧设备或消费级设备承载；如果还没有大规模真实节点环境，当前最可行的验证方案是什么。

结论先说：

- **用户节点方向：有条件成立——前提是自动 checkpoint 强制执行、持久化迁移到二进制编码、且头部用户的幂律分布尾部可控。**
- **共识节点方向：必须按专业服务器规划，且当前 2 秒出块 + 500 bundles/block 的目标在全球分布部署下有硬约束风险。**
- **当前纯 Python 实现的性能天花板远低于 250 TPS 目标，核心热路径必须迁移到编译语言才能做真实的吞吐量验证。**
- **当前最合理的验证路线不是直接上大规模真机压测，而是：**
  - 先做参数化容量建模；
  - 再做小规模真实对象尺寸测量；
  - 再做小规模 localnet 微基准；
  - 最后只把真实多机测试留给关键收口证据。

这份文档不是新的协议设计，而是对现有 `EZchain-V2-design/` 与当前 `EZ_V2/` 实现的一次容量与落地视角复核。

## 1. 结论摘要

结合当前设计与仓库实现，容量判断应分角色看。

### 1.1 用户节点

当前 V2 的核心思路是：

- 链上只承诺 sender 历史入口与状态根；
- Value 合法性主要由链下 witness 递归验证完成；
- 用户节点长期成本主要来自：
  - `TransferPackage`
  - `WitnessV2`
  - `Receipt`
  - `Checkpoint`
  - 本地钱包记录与 sidecar 保留

这条路线**理论上是可以支持端侧或消费级设备的**，但成立依赖以下前提（不是两个，而是五个）：

1. `checkpoint` 必须足够积极且接近强制性，不能让 witness 深度无限自然增长。
2. 最终正式网络与持久化编码不能长期停留在当前 Python `JSON + hex` 形态。
3. 模型的均值假设低估了幂律分布下的头部用户成本——活跃头部用户的 3 年存储可能是均值的 10-50 倍。
4. 用户侧的 `value fragmentation`（值分裂后记录数复合增长）和中间态数据（PENDING_BUNDLE / RECEIPT_MISSING）未被模型覆盖。
5. 接收侧 receipt 拉取的尾部成本未被计入——在真实 P2P 环境中，大量 receipt 会因对方离线走 pull fallback 路径。

### 1.2 共识节点

当前 V2 共识节点需要承担：

- 区块长期存储；
- receipt 窗口保留；
- bundle 提交接收；
- 区块/receipt 分发；
- HotStuff 风格投票与网络放大；
- 状态树与 diff 的持续计算。

这意味着：

- **共识节点不应继续按”消费级服务器”目标规划，应明确为”专业服务器”定位。**
- **共识节点部署位置对出块时间有硬约束——全球分布时 2 秒出块不可行，需放宽到 4-6 秒或限制共识节点地理集中度。**

如果未来目标是数千万级甚至上亿级用户规模，共识节点更应该被当作：

- 专业化节点；
- 有明确 SSD（不少于 30 TiB 可用）、1 Gbps+ 带宽、多核 CPU 预算的节点；
- 部署在低延迟互连区域（同区域 RTT < 10 ms）的节点；
- 与用户节点完全不同级别的硬件角色。

## 2. 当前仓库得到的直接证据

为避免只靠纸面推导，仓库已新增容量建模脚本：

- [scripts/v2_capacity_model.py](/Users/liwei/Code/EZchain-under-reconstruction-/scripts/v2_capacity_model.py)

它做三类事情：

1. 直接测当前 V2 真实对象尺寸；
2. 按多年期、超大规模参数外推用户节点与共识节点成本；
3. 可选跑一个小规模真实 localnet 微基准。

对应的最小回归测试：

- [EZ_Test/test_v2_capacity_model_script.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_Test/test_v2_capacity_model_script.py)

### 2.1 当前实现里最重要的容量事实

当前代码中，`Receipt.account_state_proof` 是 **256 层 SMT proof**，见：

- [EZ_V2/smt.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/smt.py)
- [EZ_V2/types.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/types.py)

并且当前持久化/网络对象大量使用：

- `dumps_json(...)`
- bytes 转 hex

见：

- [EZ_V2/serde.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/serde.py)
- [EZ_V2/storage.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/storage.py)
- [EZ_V2/consensus_store.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/consensus_store.py)

这使得当前实现期成本显著高于最终协议二进制编码成本。

### 2.2 当前脚本测得的代表性对象尺寸

代表性样本下，当前对象大小大致为：

- `Receipt`
  - protocol binary: 约 `9.48 KiB`
  - current JSON: 约 `20.61 KiB`
  - 当前实现膨胀约 `2.17x`
- `TransferPackage (1 hop)`
  - protocol binary: 约 `10.54 KiB`
  - current JSON: 约 `21.82 KiB`
- `TransferPackage (effective witness path)`
  - protocol binary: 约 `31~42 KiB`
  - current JSON: 约 `65~86 KiB`
- `Block` 每新增一个 sender entry 的增量
  - protocol binary: 约 `1.15 KiB`
  - current JSON: 约 `1.66 KiB`

这些数字不是拍脑袋估计，而是脚本按当前 `EZ_V2` 真实对象直接编码后得出。

## 3. 一组有代表性的容量判断

下面这组参数不是最终真实世界，而是一组用于判断“设计是否大致可落地”的代表性场景：

- `1000 万` 总节点
- `21` 个共识节点
- `3 年`
- `250 TPS`
- `2 秒` 出块
- 平均 value 经过 `8` 次转手
- 每 `4` 跳做一次 checkpoint

在这组输入下，脚本给出的一个代表性结果是：

### 3.1 用户节点

- 每活跃用户日均约 `108` 笔交易
- `3 年` 用户侧累计存储（模型均值）：
  - protocol binary: 约 `5.75 GiB`
  - current JSON-shaped implementation: 约 `12.08 GiB`
- 每笔 incoming transfer 的验证哈希量级：
  - 约 `1024` 次哈希

**均值估计的修正说明：**

上述 5.75 GiB 是假设所有活跃用户均匀分担交易量的结果。真实网络中用户活跃度服从幂律分布。修正估计如下：

| 用户分位 | 估计 3 年存储 (binary) | 评估 |
|---------|----------------------|------|
| 中位数用户 | 8-12 GiB（含 SQLite 开销） | 消费级 PC/笔记本可承受 |
| P90 用户 | 20-50 GiB | 需要桌面级设备或小型 NAS |
| P99 头部用户 | 50-250 GiB | 接近移动设备上限，需桌面级设备 |

- **从协议视角看，中位数和 P90 用户没有明显超出消费级设备的可承受范围。**
- **但从当前实现视角看，仍然偏胖；且 P99 头部用户的可行性取决于 checkpoint 合规率和 value fragmentation 控制效果。**
- **模型未计入 value fragmentation 的复合增长、PENDING/RECEIPT_MISSING 等中间态存储、以及 receipt pull fallback 的额外开销——这些都只会让实际数字更高。**

### 3.2 共识节点

- `3 年` 共识链长期存储：
  - protocol binary: 约 `25.34 TiB`
  - current JSON-shaped implementation: 约 `36.64 TiB`
- receipt window:
  - protocol binary: 约 `148 MiB`
  - current JSON: 约 `322 MiB`
- 单个共识节点日均进站流量：
  - protocol binary: 约 `71.85 GiB/day`
- 单个共识节点日均出站流量：
  - protocol binary: 约 `80.39 GiB/day`

这说明：

- **共识节点不适合按端侧设备目标来论证。**
- **如果项目目标真的是千万级以上长期运行，共识层必须从一开始就按专业节点资源预算设计。**

### 3.3 模型的结构性局限

当前容量模型 (`v2_capacity_model.py`) 在纯算术层面是正确的，但存在以下系统性偏差：

**a) 均值假设掩盖幂律尾部。** `sends_per_user = transfers_total / active_users` 假设所有活跃用户等额分担。真实网络的用户活跃度服从重尾分布——top 1% 用户可能承担 50%+ 的交易量。模型给出的 5.75 GiB 对中位数用户成立，但头部用户可能高出一个数量级。

**b) 未计入持久化层开销。** 协议二进制是裸数据大小，实际 SQLite 持久化包含 B-tree 页面开销（4 KiB 页）、索引、WAL 日志、碎片化，典型额外开销 20-40%。

**c) 未模拟 value fragmentation 的复合效应。** 每次 value 被分割转出，产生更多 value records，每条 record 携带独立 witness。模型只按"每笔交易一个 transfer package"计，没有模拟 value 分裂后记录数量的复合增长。

**d) 未覆盖中间态与失败路径。** PENDING_BUNDLE、RECEIPT_MISSING、LOCKED_FOR_VERIFICATION 等中间态数据，以及失败的 bundle 提交、超时回滚产生的临时数据，模型完全没有覆盖。

**e) 共识 hash 操作未转换为墙钟时间。** `consensus_hash_ops_per_bundle` 只给出了操作次数，没有与实际 CPU 性能交叉验证是否能在 block interval 内完成。

**f) receipt 同步的 pull fallback 路径未计入。** 协议"先推后拉"设计中，对方离线时的 receipt 积压、网络分区恢复后的批量同步流量尖峰，模型未覆盖。

### 3.4 与同类系统的横向参考

| 系统 | 出块时间 | 理论 TPS | 共识模型 | 共识节点硬件要求 |
|------|---------|---------|---------|---------------|
| Algorand | 3.3s | ~1,000 | 纯 VRF + BA* | 专业节点 |
| Solana | 0.4s | ~65,000 | PoH + Tower BFT | 高性能服务器（128 GB RAM, NVMe） |
| HotStuff (Diem) | ~1s | ~1,600 | 3-phase BFT | 专业节点 |
| **EZchain V2** | **2s** | **~250** | **VRF proposer + HotStuff 3-phase BFT** | **待定（见下方分析）** |

注意：EZchain V2 的 250 TPS 在数值上远低于 Solana/Diem，但每笔交易的复杂度远高于简单转账——需要 witness 递归验证、256 层 SMT 证明、多 value range 处理。直接 TPS 对比具有误导性。

## 4. 设计可行性判断

## 4.1 哪些地方是可行的

当前 V2 最有价值的点仍然成立：

- 相比 V1，不再依赖 Bloom 路线；
- sender 历史入口更精确；
- 用户验证主成本集中在局部 witness，而不是全局链上重索引；
- `checkpoint` 给了用户侧长期成本一个明确压缩杠杆；
- `bundle_sidecars` 已经开始做去重保留，而不是完全无界复制。

这些点意味着：

- 你的设计方向不是“理论上无法落地”的问题；
- 真正的问题是**参数和工程实现是否收得住**。

## 4.2 当前最大的风险点

当前真正危险的，不是协议理念，而是下面这些工程与参数风险。

### A. witness 深度增长过快

如果：

- 平均转手深度很大；
- checkpoint 不够频繁；
- 接收方又长期保留完整递归 witness；

那么用户侧长期存储和验证延迟会持续抬升。

### B. 当前 JSON 持久化过胖

当前实现里：

- receipt
- confirmed unit
- witness
- transfer package

都存在明显的 `JSON + hex` 膨胀。这个成本不代表协议本体，但会在当前阶段直接影响你的压测判断。

### C. 钱包记录层仍有重复序列化

当前钱包已经有：

- `bundle_sidecars` 表；
- `ref_count`；
- sidecar GC；

但 `value_records.record_json` 仍携带 witness 整体对象。也就是说：

- 协议层想做“sidecar 去重”；
- 当前本地持久化还没有完全吃到这个收益。

### D. 共识层长期存储没有分层

如果直接把全部区块长期全量保留在在线热存储里：

- 数千万用户规模下，长期成本会快速上升；
- 即使用户节点能轻量化，共识节点也会很重。

### E. 当前成本模型还不是包级网络仿真

现在的脚本是：

- 真实对象尺寸测量；
- 参数化外推；
- 小规模 localnet 微基准；

它还不是：

- 带 packet loss
- 带 RTT 分布
- 带重试
- 带 leader churn
- 带 adversarial peer

的完整离散事件仿真器。

所以它适合做：

- 容量边界判断；
- 参数灵敏度分析；
- 决定优化优先级；

但不能直接替代最终 TCP 多机证据。

### F. 共识延迟与吞吐量的硬约束未被建模

这是当前模型**最严重的盲区**。250 TPS + 2 秒出块 = 500 bundles/block，这在 BFT 共识下是否现实，需要做延迟分析。

每 2 秒一个 block 的共识周期内需要完成：

1. Proposer 从 mempool 选 500 个 bundles，构建 DiffEntry 列表
2. 计算 SMT 更新：500 个叶子 × 256 层 = 128,000 次哈希
3. 计算 diff_root、重新计算 state_root
4. 500 次 secp256k1 签名验证
5. 3 轮 HotStuff 网络交互（PREPARE → PRECOMMIT → COMMIT）

仅密码学计算（签名验证 + SMT 更新）在编译语言实现下约需 200-300 ms/block，留给网络交互的时间：

| 共识节点部署场景 | 单轮 RTT | 3 轮 BFT 网络耗时 | 留给计算的余量 | 可行性判断 |
|---------------|---------|-----------------|-------------|----------|
| 同机房 | ~0.5 ms | ~1.5 ms | ~1,700 ms | 充裕 |
| 同区域（同国） | ~10 ms | ~30 ms | ~1,670 ms | 可行 |
| 跨区域（邻国） | ~50 ms | ~150 ms | ~1,550 ms | 紧张但可行 |
| 跨洲 | ~150 ms | ~450 ms | ~1,250 ms | 勉强可行 |
| 含一轮超时重试 | 翻倍 | ~900+ ms | ~800 ms | **不可行** |

**结论：如果 21 个共识节点部署在同一地理区域，2 秒/500 bundles 可行；如果全球分布，需要将出块时间放宽到 4-6 秒，或降低每 block 的 bundle 数量。**

当前模型的 `consensus_hash_ops_per_bundle` 虽然计算了哈希操作次数，但没有转换为墙钟时间，没有与 block interval 做可行性交叉验证。这是一个必须补齐的分析。

### G. Python 实现的性能天花板

当前所有核心模块（chain.py、smt.py、wallet.py、consensus）都是纯 Python 实现。这带来了几个硬性约束：

1. **secp256k1 验证：** C 库实现约 0.1-0.3 ms/次，Python 纯实现可能 1-3 ms/次。500 次/block 在 Python 中需要 500-1,500 ms，已接近或超过 2 秒 block interval 的全部时间。
2. **SMT 更新：** 128,000 次哈希/块在 C/Rust 中约 128 ms，Python 中可能 5-10 秒。
3. **Keccak-256 批量计算：** Python 单线程性能约为 C 的 1/50-1/100。

**在当前 Python 实现下，250 TPS + 2 秒出块是不可达的。** 这不是参数调优问题，而是实现语言的根本限制。正式网络的共识热路径（SMT 更新、签名验证、block 构建）必须在投入真实 TCP 测试前迁移到编译语言（C/Rust/Go），否则所有吞吐量相关的压测数据都不具有参考价值。

### H. Checkpoint 合规率的非线性影响

当前 checkpoint 依赖用户主动调用 `create_exact_checkpoint()`，没有协议层强制机制。但 checkpoint 合规率对系统成本的影响是非线性的：

- 一个未 checkpoint 的 value 在后续每次转手中都携带膨胀的 witness，影响所有下游接收者
- 如果 20% 的用户不 checkpoint，受影响的不是 20% 的数据，而是这 20% 用户经手的所有 value 的全部下游链路
- 模型的 effective_witness_hops = min(avg_transfer_hops, checkpoint_interval) 假设 100% checkpoint 合规，这在真实网络中不成立

**如果 checkpoint 不是自动且接近强制的，用户节点的长期存储估计可能偏低 2-5 倍。**

### I. SMT 全局状态树随规模增长的性能衰减

256 层 SMT 随账户增长（10M 节点 = 10M 叶子）的性能特征：

- 10M 叶子的 SMT 在内存中约需 640 MiB 的叶子节点 + 中间节点
- 每次 SMT update 需要读取/写入 256 个中间节点
- 当前实现使用 Python dict 存储，更新性能约为 C/Rust 实现的 1/50-1/100
- 随着叶子数量增加，cache miss 率上升，性能进一步衰减

模型没有评估 10M+ 账户规模下 SMT 的持续更新性能。

## 5. 优化建议

建议按”先解决硬约束，再压长期成本，再补更强仿真”的顺序推进。优先级排序如下。

### 5.0 必须先解决的硬约束（blocking）

在所有其他优化之前，有两个问题不解决就无法获得有参考价值的压测数据：

1. **核心热路径迁移到编译语言。**
   以下路径的 Python 实现在 250 TPS 目标下不可行，必须在投入真实吞吐量测试前完成迁移：
   - SMT 更新与证明生成（smt.py）
   - secp256k1 签名验证（chain.py）
   - Block 构建与 state_root 重算（chain.py）
   - 共识核心轮次驱动（consensus 相关模块）
   - 可选方案：Cython/Rust（via PyO3）/CGo 扩展，保持 Python 外壳不变。

2. **明确共识节点的地理部署策略与出块时间。**
   - 如果共识节点必须全球分布：出块时间应放宽到 4-6 秒
   - 如果维持 2 秒出块：共识节点应限制在同一地理区域（RTT < 10 ms）
   - 这个决策直接影响所有后续容量计算的基准参数

### 5.1 用户侧优化建议

1. **Checkpoint 必须接近强制，不能只当可选功能。**
   建议形成项目级口径：
   - 按 hop 数触发（默认 ≤ 4 跳）；
   - 按 witness 体积触发（超过阈值自动 checkpoint）；
   - 按接收后持有时长触发；
   - 三者至少选其一作为**默认启用**策略，不允许关闭；
   - 增加协议层 checkpoint 合规率监控与告警。

2. 给钱包层增加 witness 预算与告警。
   例如：
   - 当前记录 witness 深度；
   - 当前记录 witness 估计字节数；
   - 超过阈值主动建议或自动创建 checkpoint。

3. 继续推进 sidecar / confirmed unit 去重，而不是把完整 witness 反复嵌进 `value_records`。

4. 用户节点默认保留”必要验证对象”，不要在长期热数据里重复保留可重建字段。

### 5.2 共识侧优化建议

1. 明确共识节点是专业服务器目标。
   对外口径应改成：
   - 用户节点面向消费级设备；
   - 共识节点面向专业服务器，有明确硬件最低要求（见下方）。

   建议共识节点最低硬件基准：
   - CPU: ≥ 8 核，支持 AES-NI/AVX2
   - RAM: ≥ 32 GiB（SMT 全局状态 + receipt window + mempool）
   - 存储: ≥ 30 TiB 可用 SSD（热数据）+ 可选 HDD 归档层
   - 带宽: ≥ 100 Mbps 对称（当前模型仅需 ~7 Mbps，但留足余量给突发）
   - 网络: 与其他共识节点 RTT < 50 ms

2. 给共识层增加冷热分层与归档策略。
   至少区分：
   - 热区块数据（最近 N 个 block）；
   - receipt window；
   - 可归档历史块；
   - 可外移的历史 sidecar / diff 数据。

3. 对 block / receipt / sync 消息做协议二进制编码优先，不要再用 JSON 代表最终成本。

4. 尽早做真实 TCP 多节点的带宽统计，而不是只看逻辑通过。

### 5.3 仿真与验证建议

1. 保留当前参数化模型，作为第一层快速判断。
2. 补一个离散事件仿真器，重点模拟：
   - witness hop 分布；
   - checkpoint 触发策略；
   - receipt 丢失与补拉；
   - sender/receiver 在线率；
   - 共识节点广播放大；
   - 简化的重试与超时。
3. 只在关键里程碑做真实多机验证：
   - 4 节点共识；
   - 16 节点静态网络；
   - 32~64 用户节点混合在线率；
   - 统计真实 TCP 字节数、DB 体积、CPU 时间。

## 6. 推荐验证路线

## 阶段 1：先确定“设计大方向能不能落地”

使用：

- [scripts/v2_capacity_model.py](/Users/liwei/Code/EZchain-under-reconstruction-/scripts/v2_capacity_model.py)

建议至少扫下面几组参数：

- `avg_transfer_hops = 4 / 8 / 16`
- `checkpoint_interval_hops = 2 / 4 / 8 / never`
- `tx_per_second = 10 / 50 / 250 / 1000`
- `active_user_ratio = 0.1% / 1% / 2% / 5%`
- `years = 1 / 3 / 5`

目标不是求一个最准数字，而是回答：

- 用户节点是否仍在可接受区间；
- 哪个参数最敏感；
- checkpoint 对成本的压缩有多明显；
- JSON 实现膨胀是否已经掩盖了协议真实边界。

## 阶段 2：补一个离散事件仿真器

建议放在：

- `scripts/` 或 `EZ_Test/`

目标：

- 代码规模控制在几百行到一千行以内；
- 单机几秒到几十秒可跑完；
- 可模拟千万级或上亿级逻辑节点；
- 输出不是“链是否正确”，而是：
  - witness 深度分布；
  - 用户侧平均/95 分位存储；
  - 用户侧平均/95 分位验证成本；
  - 共识侧块体积与日流量；
  - checkpoint 触发率。

建议这个仿真器只保留：

- value ownership turnover
- online/offline
- checkpoint rule
- receipt sync delay
- block cadence

不要一开始就做成完整网络栈。

## 阶段 3：做小规模真实 TCP 证据

这一步目标不是“模拟千万节点”，而是拿到真实实现证据：

- 单笔 bundle submit 的真实字节数；
- 单笔 receipt deliver 的真实字节数；
- 小规模 cluster 的真实 block fanout；
- 真实 sqlite 增长速度；
- 在重启、抖动、catch-up 下成本是否失控。

建议规模：

- 4 共识节点
- 16~32 用户节点
- 混合在线率
- 持续数小时到数天

## 7. 推荐执行计划

## 第零周（前置条件，优先于一切）

- **决策：共识节点地理部署策略。** 明确是”全球分布 + 放宽出块时间”还是”区域集中 + 维持 2 秒出块”。这个决策锁定后续所有容量计算的基准参数。
- **启动核心热路径的编译语言迁移评估。** 至少完成：SMT 更新、签名验证、block 构建三个模块的 PoC 性能对比（Python vs Rust/C）。如果 PoC 确认 10x+ 性能差距，正式列入 Phase 0 前置任务。
- **在容量模型中增加共识延迟约束验证。** 将 `consensus_hash_ops_per_bundle` 转换为墙钟时间估算，与 block interval 做交叉验证，输出”最大可行 bundles/block”的硬上界。

## 第一周

- 固定容量评估输入参数集（含第零周的出块时间决策结果）；
- 用 `v2_capacity_model.py` 跑出基线报告；
- 确定”用户节点预算”和”共识节点预算”是两条不同口径；
- 明确 checkpoint 默认策略候选方案（至少一个默认启用、不允许关闭的策略）。

## 第二周

- 给钱包层增加 witness 深度/估计字节统计；
- 增加 checkpoint 触发建议或自动策略；
- 清理本地持久化里重复 witness 序列化最明显的路径。

## 第三周

- 补离散事件仿真器；
- 扫描大参数空间；
- 形成：
  - 用户节点预算表（含 p50/p90/p99 分位）；
  - 共识节点预算表；
  - checkpoint 灵敏度曲线；
  - checkpoint 合规率对成本的灵敏度曲线。

## 第四周

- 做小规模真实 TCP 多机测试；
- 收集真实网络字节数、CPU 时间、sqlite 增长；
- 对照仿真模型修正参数；
- 如果编译语言迁移 PoC 已完成，对比 Python vs 编译语言的实测吞吐量差异。

## 第五周

- 把容量预算正式纳入 readiness 口径；
- 至少形成下面几条治理结论：
  - 用户节点目标硬件档位；
  - 共识节点最低推荐硬件；
  - 默认 checkpoint 策略（必须默认启用）；
  - 是否允许长期 JSON 持久化继续作为默认路径（建议不允许）；
  - 核心热路径编译语言迁移的时间表。

## 8. 建议的项目口径

当前更准确、更稳妥的对外口径应当是：

- EZchain V2 的**用户节点路径**有望运行在消费级设备上，但前提是自动 checkpoint 强制执行、持久化迁移到二进制编码、且头部用户的幂律分布尾部可控；
- EZchain V2 的**共识节点路径**必须按专业服务器资源预算规划，有明确硬件最低要求（CPU/RAM/SSD/带宽/网络延迟），不应再使用”消费级服务器”等模糊表述；
- **当前纯 Python 实现的吞吐量远低于 250 TPS 目标**，共识热路径（SMT、签名验证、block 构建）必须在正式测试前迁移到编译语言，否则所有吞吐量相关的压测数据不具有参考价值；
- **2 秒出块时间 + 全球分布共识节点 = 不可行**，必须在”放宽出块时间”和”限制共识节点地理范围”之间做出明确选择；
- 当前仓库已经具备做容量建模、对象尺寸测量和小规模微基准的基础；
- 但”真实 TCP 多节点长期证据”、”编译语言实现的吞吐量基准”、”共识延迟可行性验证”仍需后续补齐；
- 当前不应把”用户节点可轻量化”误表述为”所有节点都可在端侧设备上长期承载全部成本”。

## 9. 现在就可以执行的命令

快速看一组默认评估：

```bash
python3.12 scripts/v2_capacity_model.py
```

带微基准一起跑：

```bash
python3.12 scripts/v2_capacity_model.py --run-microbench
```

导出 JSON 结果，便于后续画图或做批量扫描：

```bash
python3.12 scripts/v2_capacity_model.py --json-output > /tmp/v2-capacity.json
```

## 10. 本文依据

设计依据主要来自：

- [EZchain-V2-protocol-draft.md](/Users/liwei/Code/EZchain-under-reconstruction-/EZchain-V2-design/EZchain-V2-protocol-draft.md)
- [EZchain-V2-consensus-mvp-spec.md](/Users/liwei/Code/EZchain-under-reconstruction-/EZchain-V2-design/EZchain-V2-consensus-mvp-spec.md)
- [EZchain-V2-network-and-transport-plan.md](/Users/liwei/Code/EZchain-under-reconstruction-/EZchain-V2-design/EZchain-V2-network-and-transport-plan.md)
- [EZchain-V2-small-scale-simulation.md](/Users/liwei/Code/EZchain-under-reconstruction-/EZchain-V2-design/EZchain-V2-small-scale-simulation.md)

实现依据主要来自：

- [EZ_V2/types.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/types.py)
- [EZ_V2/storage.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/storage.py)
- [EZ_V2/consensus_store.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/consensus_store.py)
- [EZ_V2/wallet.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/wallet.py)
- [EZ_V2/localnet.py](/Users/liwei/Code/EZchain-under-reconstruction-/EZ_V2/localnet.py)

## 11. 本次验证范围

本次结论基于：

- 真实对象尺寸测量；
- 参数化容量外推；
- 小规模 localnet 微基准；
- 对模型假设的结构性偏差分析；
- 共识延迟与吞吐量的硬约束推导；
- 与同类 BFT 系统的横向对比。

已经运行：

- `python3.12 -m unittest EZ_Test.test_v2_capacity_model_script`
- `python3.12 scripts/v2_capacity_model.py --run-microbench`

本次**没有**运行：

- 大规模真实 TCP 多机压测；
- 长周期多天级真实网络 soak test；
- 完整 release / consensus / stability 门禁；
- 包级网络离散事件仿真；
- 编译语言实现下的真实吞吐量基准测试；
- 不同地理分布场景下的共识延迟实测。

### 11.1 已知遗漏与修正方向

| 遗漏项 | 影响 | 修正优先级 |
|-------|------|----------|
| 模型均值假设未考虑幂律分布 | 头部用户成本被低估 2-10x | 高（需补 p95/p99 估计） |
| 共识延迟未与出块时间交叉验证 | 2 秒出块的可行性判断缺乏依据 | **最高** |
| Python 实现性能天花板未正面讨论 | 250 TPS 目标的可达性判断失真 | **最高** |
| Checkpoint 合规率未建模 | 用户存储估计偏低 2-5x | 高 |
| Value fragmentation 未建模 | 用户记录数复合增长未计入 | 中 |
| Receipt pull fallback 成本未计入 | 用户/共识网络成本被低估 | 中 |
| SMT 规模增长性能衰减未评估 | 共识计算时间随账户增长可能超预期 | 中 |

因此，这份文档的定位是：

- **落地前容量判断与优化计划（含已知偏差说明）**

而不是：

- **最终正式测试网容量证据**

文档中的数值在纯算术层面正确，但用户侧存储估计应理解为**乐观下界**，共识侧吞吐量可行性需在编译语言实现后重新验证。
