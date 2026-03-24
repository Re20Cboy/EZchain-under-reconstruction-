# V2 Capacity Assessment And Optimization Plan

本文件回答一个落地前的关键问题：

> EZchain V2 在真实分布式 P2P 环境长期运行后，共识节点和用户节点的存储、计算、通信成本，是否仍能被端侧设备或消费级设备承载；如果还没有大规模真实节点环境，当前最可行的验证方案是什么。

结论先说：

- **用户节点方向：有机会成立。**
- **共识节点方向：按当前协议与实现形态，不应再以“普通消费级端侧设备”作为默认目标。**
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

这条路线**理论上是可以支持端侧或消费级设备的**，但成立依赖两个前提：

1. `checkpoint` 必须足够积极，不能让 witness 深度无限自然增长。
2. 最终正式网络与持久化编码不能长期停留在当前 Python `JSON + hex` 形态。

### 1.2 共识节点

当前 V2 共识节点需要承担：

- 区块长期存储；
- receipt 窗口保留；
- bundle 提交接收；
- 区块/receipt 分发；
- HotStuff 风格投票与网络放大；
- 状态树与 diff 的持续计算。

这意味着：

- **共识节点可以是“消费级服务器”目标；**
- **但不应继续按“轻量端侧设备”目标规划。**

如果未来目标是数千万级甚至上亿级用户规模，共识节点更应该被当作：

- 专业化节点；
- 有明确 SSD、带宽、CPU 预算的节点；
- 与用户节点不同级别的硬件角色。

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
- `3 年` 用户侧累计存储：
  - protocol binary: 约 `5.75 GiB`
  - current JSON-shaped implementation: 约 `12.08 GiB`
- 每笔 incoming transfer 的验证哈希量级：
  - 约 `1024` 次哈希

这说明：

- **从协议视角看，用户节点并没有明显超出消费级 PC / 笔记本 / 高配移动设备 / 小型家用 NAS 的可承受范围。**
- **从当前实现视角看，仍然偏胖，但不是完全不可落地。**

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

## 5. 优化建议

建议按“先压用户侧长期成本，再压共识侧长期成本，再补更强仿真”的顺序推进。

### 5.1 用户侧优化建议

1. 明确 checkpoint 策略，不再只把它当可选功能。
   建议至少形成项目级口径：
   - 按 hop 数触发；
   - 按 witness 体积触发；
   - 按接收后持有时长触发；
   - 三者至少选其一作为默认策略。

2. 给钱包层增加 witness 预算与告警。
   例如：
   - 当前记录 witness 深度；
   - 当前记录 witness 估计字节数；
   - 超过阈值主动建议创建 checkpoint。

3. 继续推进 sidecar / confirmed unit 去重，而不是把完整 witness 反复嵌进 `value_records`。

4. 用户节点默认保留“必要验证对象”，不要在长期热数据里重复保留可重建字段。

### 5.2 共识侧优化建议

1. 明确共识节点不是端侧目标。
   对外口径应改成：
   - 用户节点面向消费级设备；
   - 共识节点面向专业节点或轻服务器。

2. 给共识层增加冷热分层与归档策略。
   至少区分：
   - 热区块数据；
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

## 第一周

- 固定容量评估输入参数集；
- 用 `v2_capacity_model.py` 跑出基线报告；
- 确定“用户节点预算”和“共识节点预算”是两条不同口径；
- 明确 checkpoint 默认策略候选方案。

## 第二周

- 给钱包层增加 witness 深度/估计字节统计；
- 增加 checkpoint 触发建议或自动策略；
- 清理本地持久化里重复 witness 序列化最明显的路径。

## 第三周

- 补离散事件仿真器；
- 扫描大参数空间；
- 形成：
  - 用户节点预算表；
  - 共识节点预算表；
  - checkpoint 灵敏度曲线。

## 第四周

- 做小规模真实 TCP 多机测试；
- 收集真实网络字节数、CPU 时间、sqlite 增长；
- 对照仿真模型修正参数。

## 第五周

- 把容量预算正式纳入 readiness 口径；
- 至少形成下面几条治理结论：
  - 用户节点目标硬件档位；
  - 共识节点最低推荐硬件；
  - 默认 checkpoint 策略；
  - 是否允许长期 JSON 持久化继续作为默认路径。

## 8. 建议的项目口径

当前更准确、更稳妥的对外口径应当是：

- EZchain V2 的**用户节点路径**有望运行在消费级设备上；
- EZchain V2 的**共识节点路径**默认应按专业节点资源预算规划；
- 当前仓库已经具备做容量建模、对象尺寸测量和小规模微基准的基础；
- 但“真实 TCP 多节点长期证据”仍需后续补齐；
- 当前不应把“用户节点可轻量化”误表述为“所有节点都可在端侧设备上长期承载全部成本”。

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

已经运行：

- `python3.12 -m unittest EZ_Test.test_v2_capacity_model_script`
- `python3.12 scripts/v2_capacity_model.py --run-microbench`

本次**没有**运行：

- 大规模真实 TCP 多机压测；
- 长周期多天级真实网络 soak test；
- 完整 release / consensus / stability 门禁；
- 包级网络离散事件仿真。

因此，这份文档的定位是：

- **落地前容量判断与优化计划**

而不是：

- **最终正式测试网容量证据**
