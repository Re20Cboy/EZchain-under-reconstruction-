# EZchain-V2 单元测试优先推进计划

本计划用于把 `EZchain-V2` 的验证主轴，从“继续扩大分布式联调”切回到“先校正设计语义、再稳模块测试、最后恢复分布式验证”。

这不是状态汇报，也不是一次性 TODO。它是后续一段时间内的长期执行清单，目的是避免我们继续在错误的测试口径、错误的模块语义、或错误的分布式基线上叠加工作。

当前默认结论：

- 在完成模块级测试审计与关键缺口补齐前，不把分布式 batch、长跑、checkpoint 效率结论当成正式证据。
- 现有 V2 测试可以参考，但不自动视为“已证明符合设计”。
- 后续任何恢复大规模双机或多机场景的动作，都必须以本计划中的波次退出标准为前提。

## 1. 背景与原则

当前仓库已经积累了不少 V2 测试与分布式脚本，但近期联调暴露出一个核心问题：

- 某些行为“能跑通”，不等于“符合 V2-design 原意”
- 某些测试“能通过”，不等于“它在验证正确语义”
- 某些分布式现象“看起来合理”，也可能只是底层 drift 被脚本或时序掩盖了

因此，后续推进遵循以下原则：

1. 先看设计，再看测试，再看实现。
2. 先修测试口径，再补测试缺口，再恢复更大规模联调。
3. 不把顺序 batch、即时出块、脚本默认行为误当成协议设计证据。
4. 单元层与小集成层先证明“语义正确”，分布式层只证明“跨机现实与运维现实”。
5. 所有测试都要明确自己验证的是：
   - 设计明确要求
   - 当前实现的临时行为
   - 不应被固化的偶然行为

## 2. 设计对照来源

后续判断以以下文档为主，不以当前实现是否“能运行”替代设计判断。

### 2.1 核心设计来源

- `EZchain-V2-design/EZchain-V2-protocol-draft.md`
- `EZchain-V2-design/EZchain-V2-consensus-mvp-spec.md`
- `EZchain-V2-design/EZchain-V2-small-scale-simulation.md`
- `EZchain-V2-design/EZchain-V2-node-role-and-app-boundary.md`
- `EZchain-V2-design/EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-design/EZchain-V2 desgin-human-write.md`

### 2.2 当前治理与验证口径

- `AGENTS.md`
- `doc/V2_DEFAULT_READINESS.md`
- `doc/DEV_TESTING.md`

### 2.3 统一分类标签

本计划中的模块、测试、行为统一使用下面 4 个标签：

- `aligned`
- `temporary divergence`
- `drift`
- `unclear`

含义如下：

- `aligned`：当前实现与测试已经与设计一致
- `temporary divergence`：当前实现暂时不同，但原因明确、边界明确，且不能当成最终设计
- `drift`：当前实现或测试已经偏离设计，应被纠正
- `unclear`：当前仓库现实还不足以判断，需要先审计

## 3. 模块级测试总表

下表是第一版“设计对照型”模块总表。它不是最终结论，而是后续审计的起点。

| 模块/子系统 | owning layer | source of truth | current tests | 当前初始判断 | next action | 单元层退出标准 |
| --- | --- | --- | --- | --- | --- | --- |
| `EZ_V2/types.py` | `EZ_V2` | protocol draft, small-scale simulation | `test_ez_v2_protocol.py`, `test_ez_v2_crypto.py` | `unclear` | `audit` | 关键协议对象构造、序列化、篡改失败、引用关系有 focused tests |
| `EZ_V2/values.py` | `EZ_V2` | protocol draft, design-human-write | `test_ez_v2_protocol.py`, `test_ez_v2_runtime.py`, `test_ez_v2_wallet_storage.py` | `unclear` | `audit` | value/value-range 守恒、切分、合并、边界行为被覆盖 |
| `EZ_V2/chain.py` | `EZ_V2` | protocol draft, small-scale simulation | `test_ez_v2_protocol.py`, `test_ez_v2_runtime.py`, `test_ez_v2_network.py`, `test_ez_v2_wallet_storage.py`, `test_ez_v2_consensus_*` | `unclear` | `audit` | bundle pool、block build、receipt/ref 绑定、mempool 规则被单独证明 |
| `EZ_V2/validator.py` | `EZ_V2` | protocol draft | `test_ez_v2_protocol.py`, `test_ez_v2_wallet_storage.py` | `unclear` | `audit` | witness/receipt/state proof 校验边界明确且带负向测试 |
| `EZ_V2/wallet.py` | `EZ_V2` | protocol draft, small-scale simulation | `test_ez_v2_protocol.py`, `test_ez_v2_wallet_storage.py`, `test_ez_v2_network.py`, `test_ez_v2_runtime.py` | `unclear` | `audit` | confirmed bundle chain、checkpoint、收付款状态转换被 focused tests 证明 |
| `EZ_V2/storage.py` | `EZ_V2` | protocol draft | 暂由 `test_ez_v2_wallet_storage.py`, `test_ez_v2_runtime.py` 间接覆盖 | `unclear` | `add tests` | 落盘、重载、幂等、损坏/缺项恢复路径被直接测试 |
| `EZ_V2/consensus_store.py` | `EZ_V2` | consensus spec | `test_ez_v2_consensus_store.py` | `unclear` | `audit` | round/height/QC/validator-set 相关持久化与恢复正确 |
| `EZ_V2/smt.py` | `EZ_V2` | design-human-write, protocol draft | 当前缺专门 focused tests | `unclear` | `add tests` | root、proof、update、tamper-fail 被 focused tests 覆盖 |
| `EZ_V2/crypto.py` | `EZ_V2` | consensus spec, protocol draft | `test_ez_v2_crypto.py`, `test_ez_v2_consensus_sortition.py` | `aligned` 倾向但需审计 | `audit` | vote key、VRF key、签名与验证用途隔离明确 |
| `EZ_V2/encoding.py`, `EZ_V2/serde.py` | `EZ_V2` | protocol draft | 当前分散覆盖 | `unclear` | `add tests` | 协议字段编码稳定、前后兼容边界明确 |
| `EZ_V2/runtime_v2.py` | `EZ_V2` | consensus spec, node-role-and-app-boundary | `test_ez_v2_runtime.py`, `test_ez_v2_consensus_runner.py` | `unclear` | `audit` | 共识驱动与状态推进的 owning boundary 明确 |
| `EZ_V2/consensus/core.py`, `pacemaker.py`, `runner.py`, `sortition.py`, `validator_set.py`, `store.py` | `EZ_V2` | consensus spec | `test_ez_v2_consensus_core.py`, `test_ez_v2_consensus_pacemaker.py`, `test_ez_v2_consensus_runner.py`, `test_ez_v2_consensus_sortition.py`, `test_ez_v2_consensus_validator_set.py`, `test_ez_v2_consensus_store.py` | `unclear` | `audit` | proposer、vote、QC、round 推进、validator set 语义与 spec 对齐 |
| `EZ_V2/network_host.py` | `EZ_V2` | consensus spec, network-and-transport plan, small-scale simulation | `test_ez_v2_network.py`, `test_ez_v2_consensus_sync.py`, `test_ez_v2_consensus_catchup.py`, `test_ez_v2_submit_failure_recovery.py` | `temporary divergence` 与 `drift` 并存 | `rewrite tests` | submit、snapshot window、sync、receipt best-effort、catch-up 路径被拆开验证 |
| `EZ_V2/networking.py`, `network_transport.py`, `transport.py`, `transport_peer.py` | `EZ_V2` | network-and-transport plan | `test_ez_v2_transport.py`, `test_ez_v2_network.py`, `test_ez_v2_consensus_tcp_catchup.py` | `unclear` | `audit` | transport 失败模式与上层语义边界清楚，不同 adapter 结果一致 |
| `EZ_App/runtime.py` | `EZ_App` | node-role-and-app-boundary, protocol draft | `test_ez_v2_app_runtime.py`, `test_ez_v2_runtime.py` | `temporary divergence` 风险较高 | `audit` | app 仅负责 wiring，不偷偷改 chain_id、peer_id、timeout、语义 |
| `EZ_App/wallet_store.py` | `EZ_App` | node-role-and-app-boundary | `test_ez_v2_app_runtime.py`, `test_ez_v2_node_manager.py` | `unclear` | `audit` | app 层钱包目录、状态存取、V2 路径边界清晰 |
| `EZ_App/node_manager.py` | `EZ_App` | node-role-and-app-boundary | `test_ez_v2_node_manager.py` | `unclear` | `audit` | start/stop/restart/status 判定与真实进程状态一致 |
| `scripts/` 中 V2 验证脚本 | `scripts` | AGENTS, readiness docs, design docs | `test_v2_two_host_cluster.py`, `test_v2_tcp_scale_scenario.py` 等 | `temporary divergence` | `defer` | 仅在前 0-5 波完成后再重新评估脚本验证职责 |

## 4. 分波推进计划

后续推进固定成 7 波，不允许为了赶联调而跳波。

### 第 0 波：测试口径审计层

这一波先不急着补新测试，而是先判断“现有测试是不是在证明错误行为”。

#### 4.0.1 覆盖对象

- `EZ_Test/test_ez_v2_protocol.py`
- `EZ_Test/test_ez_v2_wallet_storage.py`
- `EZ_Test/test_ez_v2_runtime.py`
- `EZ_Test/test_ez_v2_network.py`
- `EZ_Test/test_ez_v2_consensus_*`

#### 4.0.2 审计动作

每个测试文件都要补一份最小审计记录，记录以下内容：

- 这个测试文件想证明哪条设计语义
- 它当前断言的是：
  - 设计明确要求
  - 当前实现临时行为
  - 不应固化的偶然行为
- 是否存在“测试通过但设计不一定对”的情况
- 是否需要拆分为更小的 focused tests

#### 4.0.3 需要形成的输出

每个文件至少形成一条结论：

- `aligned`
- `temporary divergence`
- `drift`
- `unclear`

同时为每个文件补一个 `next action`：

- `keep`
- `rewrite`
- `split`
- `defer`

#### 4.0.4 第 0 波退出标准

- 上述测试文件全部完成可信度分类
- 不再存在“我们不知道这条测试到底在验证什么”的文件
- 第 1 波开始前，先列出至少一份“必须重写的测试文件名单”

### 第 1 波：协议与数据模型核心

这一波先稳底层，不让上层测试建立在错误状态模型上。

#### 4.1.1 覆盖模块

- `EZ_V2/types.py`
- `EZ_V2/values.py`
- `EZ_V2/chain.py`
- `EZ_V2/validator.py`
- `EZ_V2/wallet.py`
- `EZ_V2/storage.py`
- `EZ_V2/consensus_store.py`
- `EZ_V2/smt.py`
- `EZ_V2/crypto.py`
- `EZ_V2/encoding.py`
- `EZ_V2/serde.py`

#### 4.1.2 设计依据

- `EZchain-V2-protocol-draft.md`
- `EZchain-V2 desgin-human-write.md`
- `EZchain-V2-small-scale-simulation.md`

#### 4.1.3 必测语义

- value / value-range 守恒
- sender 历史递归验证边界
- `confirmed_bundle_chain` 语义
- receipt / `prev_ref` / `block_hash` 绑定
- checkpoint exact-range 语义
- bundle sidecar 去重与 `bundle_hash` 一致性
- 每 sender 最多一个 mempool bundle
- 存储重启后状态不丢、不重放、不串链
- 密钥用途隔离，不混用 vote key / VRF key

#### 4.1.4 测试组织要求

每个模块都按下列类型建或重写 focused tests：

1. `design-conformance`
2. `negative / adversarial`
3. `restart / persistence`
4. `boundary / invariants`
5. `temporary divergence`

#### 4.1.5 建议新增或拆分的测试文件

- `EZ_Test/test_ez_v2_types.py`
- `EZ_Test/test_ez_v2_values_core.py`
- `EZ_Test/test_ez_v2_bundle_pool.py`
- `EZ_Test/test_ez_v2_receipts.py`
- `EZ_Test/test_ez_v2_checkpoint_core.py`
- `EZ_Test/test_ez_v2_storage_restart.py`
- `EZ_Test/test_ez_v2_smt.py`
- `EZ_Test/test_ez_v2_encoding.py`

如果不新增文件，也至少要把现有超大测试文件拆成按语义组织的小测试段落。

#### 4.1.6 第 1 波退出标准

- 协议对象已覆盖到：构造、序列化、持久化、重载、篡改失败
- checkpoint、receipt、bundle_ref 不再只靠集成测试证明
- 底层 invariants 不再混在 network/runtime 大测试里

### 第 2 波：共识核心状态机

这一波只测共识语义，不掺 transport 与真实双机问题。

#### 4.2.1 覆盖模块

- `EZ_V2/consensus/core.py`
- `EZ_V2/consensus/pacemaker.py`
- `EZ_V2/consensus/runner.py`
- `EZ_V2/consensus/sortition.py`
- `EZ_V2/consensus/validator_set.py`
- `EZ_V2/consensus/store.py`
- `EZ_V2/runtime_v2.py`
- `EZ_V2/network_host.py` 中直接承担共识状态机责任的部分

#### 4.2.2 对应测试

- `EZ_Test/test_ez_v2_consensus_core.py`
- `EZ_Test/test_ez_v2_consensus_pacemaker.py`
- `EZ_Test/test_ez_v2_consensus_runner.py`
- `EZ_Test/test_ez_v2_consensus_sortition.py`
- `EZ_Test/test_ez_v2_consensus_validator_set.py`
- `EZ_Test/test_ez_v2_consensus_store.py`

#### 4.2.3 设计依据

- `EZchain-V2-consensus-mvp-spec.md`
- `EZchain-V2-small-scale-simulation.md`

#### 4.2.4 必测语义

- proposer sortition 输入与 seed 绑定
- validator set 许可型边界
- proposal / vote / QC 合法性
- pacemaker round 推进
- commit 只能基于正确 QC
- restart 后 round / height / locked state 不错乱
- auto-run 应采用 snapshot window，而不是 one-submit-one-round
- 同窗口多 sender 能形成同块多 bundle
- `snapshot_cutoff` 后到达 bundle 自动进入下一轮

#### 4.2.5 重点审计点

以下行为不能直接视为正确，而必须显式对照设计：

- “收到一笔 bundle 就立即开一轮”
- “单笔顺序 batch 形成多块”被误当成 mempool 正常工作
- proposer 选择逻辑与 round/height/seed 脱钩

#### 4.2.6 建议新增 focused tests

- `EZ_Test/test_ez_v2_consensus_snapshot_window.py`
- `EZ_Test/test_ez_v2_consensus_block_packing.py`
- `EZ_Test/test_ez_v2_consensus_qc_rules.py`

#### 4.2.7 第 2 波退出标准

- 共识核心能在纯内存或静态网络模型下证明“批量 snapshot 出块”
- 不再把“逐笔触发立即出块”当成正确行为
- proposer / vote / QC / round 语义都有单独 focused tests

### 第 3 波：同步、catch-up、恢复

这一波专门验证“节点掉队、重启、缺块、缺 receipt”时的正确性。

#### 4.3.1 覆盖模块

- `EZ_V2/network_host.py` 中 sync / catch-up 路径
- `EZ_V2/networking.py`
- `EZ_V2/network_transport.py`
- `EZ_V2/transport.py`
- `EZ_V2/transport_peer.py`

#### 4.3.2 对应测试

- `EZ_Test/test_ez_v2_consensus_sync.py`
- `EZ_Test/test_ez_v2_consensus_catchup.py`
- `EZ_Test/test_ez_v2_consensus_tcp_catchup.py`
- `EZ_Test/test_ez_v2_submit_failure_recovery.py`
- `EZ_Test/test_ez_v2_transport.py`

#### 4.3.3 设计依据

- `EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-consensus-mvp-spec.md`

#### 4.3.4 必测语义

- block fetch / receipt sync / checkpoint req/resp
- account / consensus 恢复后状态收敛
- sender 提交失败不能留下脏 pending
- receipt push 失败应 best-effort，不能破坏 commit
- transport 超时、断流、半读、重复请求处理
- 不同 transport adapter 不改变上层协议语义

#### 4.3.5 建议新增 focused tests

- `EZ_Test/test_ez_v2_receipt_sync.py`
- `EZ_Test/test_ez_v2_checkpoint_sync.py`
- `EZ_Test/test_ez_v2_transport_failures.py`
- `EZ_Test/test_ez_v2_account_recovery.py`

#### 4.3.6 第 3 波退出标准

- 能在单元/小集成层稳定复现并验证恢复路径
- 提交失败、半读、断流、receipt 缺失都有 focused regression
- 不再依赖真实双机环境去发现基础恢复 bug

### 第 4 波：账户运行时与应用边界

这一波确认 `EZ_App` 不会重新定义 V2 语义。

#### 4.4.1 覆盖模块

- `EZ_App/runtime.py`
- `EZ_App/wallet_store.py`
- `EZ_App/node_manager.py`
- 相关 CLI / app wiring

#### 4.4.2 对应测试

- `EZ_Test/test_ez_v2_app_runtime.py`
- `EZ_Test/test_ez_v2_runtime.py`
- `EZ_Test/test_ez_v2_node_manager.py`
- `EZ_Test/test_ez_v2_genesis_bootstrap.py`

#### 4.4.3 设计依据

- `EZchain-V2-node-role-and-app-boundary.md`
- `EZchain-V2-protocol-draft.md`

#### 4.4.4 必测语义

- app 层只做 wiring，不篡改协议含义
- chain_id、peer_id、timeout、wallet 路径都来自显式配置
- remote send / balance / recovery 的状态解释一致
- genesis bootstrap 不引入额外账户语义
- node manager 的 restart / state file / health 判断准确

#### 4.4.5 重点风险

以下问题必须单独有测试守住：

- app 默认值偷偷改变 V2 协议行为
- peer_id、chain_id、timeout、wallet 路径从错误来源继承
- runtime 返回的是临时状态，但上层误当成最终状态

#### 4.4.6 第 4 波退出标准

- 所有账户侧“提交、同步、确认、恢复”行为都能在单元或小范围进程测试里解释清楚
- app 层不再通过默认值偷偷改变 V2 协议行为

### 第 5 波：checkpoint 与效率收益专项

这一波单独做，不与“基本正确性”混在一起。

#### 4.5.1 设计依据

- `EZchain-V2-protocol-draft.md`
- `EZchain-V2-small-scale-simulation.md`

#### 4.5.2 必须拆成两部分

1. `correctness`
2. `effectiveness`

#### 4.5.3 correctness 必测

- exact-range checkpoint 创建条件
- `checkpoint_height + checkpoint_block_hash + checkpoint_bundle_hash` 绑定
- partial overlap 明确不支持
- checkpoint 后 witness 裁剪语义正确

#### 4.5.4 effectiveness 必测

- 有/无 checkpoint 时 witness 长度对比
- recipient 验证输入大小对比
- catch-up / recovery 耗时差异
- 值选择策略是否真的提高 checkpoint 触发机会

#### 4.5.5 建议新增测试与证据项

- `EZ_Test/test_ez_v2_checkpoint_correctness.py`
- `EZ_Test/test_ez_v2_checkpoint_effectiveness.py`
- 如果需要额外证据采集，再考虑补脚本，但脚本只服务于数据采集，不代替正确性判断

#### 4.5.6 第 5 波退出标准

- 先证明 checkpoint “对”，再证明 checkpoint “有收益”
- 在收益证据出来前，不把 checkpoint 当成性能结论

### 第 6 波：恢复分布式联调的准入条件

只有前面各波满足后，才恢复更大规模双机或多机联调。

#### 4.6.1 准入门槛

- 第 0 波完成，现有测试已分类
- 第 1、2、3、4 波核心阻断项清零
- checkpoint correctness 至少通过
- 每个波次都有 focused tests，且能稳定重复
- 分布式脚本只验证“跨机与运维现实”，不再承担设计定性的职责

#### 4.6.2 恢复顺序

1. 单机多节点静态网络
2. 单机 TCP 多节点
3. 双机顺序 batch
4. 双机 burst / mempool packing
5. 长时间稳定性
6. checkpoint 效率实证

#### 4.6.3 明确禁止的回退做法

在前 0-5 波完成前，不允许把以下结果当成正式设计证据：

- “双机上能跑几笔”
- “tx-batch 看起来大多数 confirmed”
- “checkpoint 在日志里出现过”
- “脚本输出有 success 字段”

这些都只能算运行现象，不能取代设计一致性证明。

## 5. 测试清单组织规则

从本计划开始，V2 单元测试统一按以下 5 类组织：

### 5.1 design-conformance

直接对照设计语义的正向测试。

### 5.2 negative / adversarial

覆盖：

- 篡改
- 重放
- 断链
- 签名错误
- 哈希不一致
- 范围越界
- 重复提交

### 5.3 restart / persistence

覆盖：

- 落盘
- 重启
- recover
- 重复加载
- 半完成状态恢复

### 5.4 boundary / invariants

覆盖：

- 空集合
- 单元素
- 多 sender
- exact-range
- 跨高度
- 跨轮次

### 5.5 temporary divergence

当前实现临时存在、但未来应移除的行为，必须单独标注，不能混入“正确性通过”口径。

## 6. 每一波的交付要求

每一波都必须在本文档中回写：

- `status`
- `checked files`
- `blocking issues`
- `evidence commands`
- `temporary divergences`
- `next wave`

每一波结束时都必须显式列出：

- 新增或重写了哪些 `EZ_Test/test_ez_v2_*.py`
- 哪些测试被拆分
- 哪些老测试先保留但标记成 `temporary divergence`
- 最小验证命令
- 阻断项是否清零

## 7. 最小验证命令建议

本节不是立即全部执行，而是给后续每波推进时提供最小验证起点。

### 7.1 第 0 波：审计阶段

优先只跑受影响测试文件，不跑大而全 gate。

示例：

```bash
python3 -m pytest EZ_Test/test_ez_v2_protocol.py -q
python3 -m pytest EZ_Test/test_ez_v2_wallet_storage.py -q
python3 -m pytest EZ_Test/test_ez_v2_runtime.py -q
python3 -m pytest EZ_Test/test_ez_v2_network.py -q
python3 -m pytest EZ_Test/test_ez_v2_consensus_core.py -q
```

### 7.2 第 1-4 波：focused tests 优先

遵循：

1. 先跑最近测试文件
2. 再跑相关 grouped regression
3. 只在风险上升时再跑 acceptance / gate

### 7.3 第 5 波：checkpoint correctness 与 effectiveness 分开

- correctness 可以用 focused tests 验证
- effectiveness 允许用小规模受控场景辅助采样
- 但 effectiveness 不得替代 correctness

### 7.4 第 6 波：恢复分布式联调前

只有当前 0-5 波文档记录完整、阻断项清零后，才允许恢复双机或多机路径。

## 8. 执行记录模板

后续每推进完一波，按以下模板回写本文档对应章节。

```md
### Wave X 更新记录

- status:
- checked files:
- design refs:
- findings:
- temporary divergences:
- new or rewritten tests:
- evidence commands:
- blocking issues:
- next wave:
```

## 9. 当前默认执行顺序

从现在开始，默认按以下顺序推进，不再跳步：

1. 第 0 波：测试口径审计
2. 第 1 波：协议 / 钱包 / 存储 / 数据模型
3. 第 2 波：共识核心状态机
4. 第 3 波：sync / catch-up / recovery
5. 第 4 波：app runtime / wallet store / node manager
6. 第 5 波：checkpoint correctness + effectiveness
7. 第 6 波：恢复分布式联调

只有这个顺序，不再为了联调进度把基础语义验证往后推。
