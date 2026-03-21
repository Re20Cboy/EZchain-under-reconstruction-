# EZchain-V2 实施路线图

## 0. 文档目的

本文档不是新的协议草案，而是面向当前仓库代码现实的一份实施路线图。

它回答四个工程问题：

1. `EZ_V2` 目前已经做到哪里；
2. 现在最应该继续做什么；
3. 后续应该按什么顺序落地，才能真正形成可运行的 V2 项目；
4. 何时开始替换现有 V1 主路径，何时仍应保持双轨并行。

本文档以以下文档为上位约束：

- `EZchain-V2-protocol-draft.md`
- `EZchain-V2-module-migration-checklist.md`
- `EZchain-V2-small-scale-simulation.md`
- `EZchain-V2-network-and-transport-plan.md`
- `EZchain-V2-node-role-and-app-boundary.md`

---

## 1. 当前项目现状判断

### 1.1 已完成的 V2 基础能力

当前仓库中的 `EZ_V2` 已经具备以下能力：

1. 规范编码、Keccak、签名与哈希基础；
2. `BundleEnvelope / BundleSidecar / Receipt / ConfirmedBundleUnit / WitnessV2` 等 V2 协议对象；
3. Sparse Merkle Tree、`ChainStateV2`、`BundlePool`、`ReceiptCache`；
4. `V2TransferValidator` 递归验证器；
5. `LocalWalletDB` 与 `WalletAccountV2`；
6. 应用层最小接入：
   - `EZ_App/runtime.py` 已可通过 `protocol_version=v2` 驱动 V2 钱包；
   - `WalletStore` 已可基于同一助记词派生 V2 身份。

### 1.2 当前最大的缺口

当前最大的缺口不是“对象定义不完整”，而是：

> `EZ_V2` 仍然没有进入真实节点主循环。

也就是说，以下真实运行主路径仍然是 V1：

- `run_ez_p2p_network.py`
- `modules/ez_p2p/nodes/consensus_node.py`
- `modules/ez_p2p/nodes/account_node.py`
- `modules/ez_p2p/adapters/txpool_adapter.py`
- `EZ_Main_Chain/Blockchain.py`
- `EZ_Tx_Pool/TXPool.py`
- `EZ_Transaction/SubmitTxInfo.py`
- `EZ_VPB_Validator/`

因此当前系统仍然依赖：

- `SubmitTxInfo`
- `TXPool`
- `PickTx`
- `Block + Bloom + Merkle`
- `VPB_TRANSFER`
- `VPBValidator`

这意味着：

1. V2 钱包虽然可以生成 pending bundle，但没有真正提交给 V2 共识执行路径；
2. sender 虽然可构造 bundle，但 Receipt 还没有通过真实节点路径返回；
3. recipient 虽然已有 V2 验证器，但当前账户节点主循环仍是 `VPB_TRANSFER`；
4. 当前的 “V2 接入” 仍是局部接入，不是系统接入。

### 1.3 工程结论

从整个项目的宏观视角看，当前最优先的工作不是继续扩钱包接口，也不是继续改 CLI/UI，而是：

> 先建立一条独立、可运行、可验证的 V2 端到端闭环。

---

## 2. 总体迁移策略

### 2.1 采用双轨并行，而不是原地替换

后续 V2 落地采用：

- `V1 保持可运行`
- `V2 独立成线`
- `V2 闭环稳定后再替换主入口`

不采用以下做法：

1. 在现有 `modules/ez_p2p/nodes/account_node.py` 内同时维护 V1/V2 双协议状态机；
2. 在 V1 `Blockchain / TXPool / SubmitTxInfo / VPBValidator` 上继续叠加兼容语义；
3. 让 `EZ_V2` 反向依赖 V1 的核心协议对象。

### 2.2 V2 运行边界

V2 的正式运行边界固定为：

- `WalletAccountV2`
- `LocalWalletDB`
- `BundleEnvelope / BundleSidecar / BundlePool`
- `ChainStateV2`
- `Receipt / ConfirmedBundleUnit / WitnessV2`
- `V2TransferValidator`

V1 仅允许继续提供以下可复用能力：

- 工具函数
- 配置与应用层外壳
- SQLite 工程模式
- 对象池 / 映射表 / sequence 的存储经验

### 2.3 实施红线

以下内容在 V2 主路径中不得继续存在：

1. `pickle` 参与的网络协议或签名输入；
2. 任何依赖 Bloom 的历史合法性验证；
3. 任何把 `ProofUnit` 包装成 V2 对象的兼容层；
4. `EZ_V2` 反向 import V1 的：
   - `VPBManager`
   - `VPBValidator`
   - `TXPool`
   - `SubmitTxInfo`
   - `BlockIndexList`
5. 在现有 V1 核心对象上继续新增 V2 状态字段。

### 2.4 MVP 默认约束

V2 MVP 明确采用以下默认值：

1. Checkpoint 只支持 exact-range；
2. 先做单 leader / 单共识节点 runtime，不先做复杂 leader 竞争；
3. 先做 sender receipt 闭环，再做 recipient 收款闭环；
4. Receipt 缓存采用最近 `R` 块窗口；
5. 继续允许当前临时签名侧信息存在，但后续可独立替换为 recoverable 签名。

---

## 3. 推荐实施顺序

后续应严格按以下阶段推进。

如果跳过阶段顺序，会导致应用层、P2P 层和主链层反复返工。

### 阶段 0：冻结 V2 运行语义

#### 目标

在开始大规模接入前，把当前草案中仍会影响实现的关键点固定成工程规则。

#### 必须冻结的规则

1. `Receipt` 到账后的追加范围；
2. `acquisition_boundary` 的定义；
3. `BundleSidecar` 的持久化与 GC 规则；
4. `snapshot_cutoff` 的 mempool 边界；
5. `UNFINALIZED Receipt` 的最小确认深度；
6. exact-range checkpoint 的边界与不支持事项。

#### 产出

1. 本文档作为总路线图；
2. 若有必要，补一份 `V2 MVP supplement`，只记录未决工程口径；
3. 所有后续阶段必须引用同一组默认规则。

#### 验收

- V2 的运行语义不再需要实现者临时拍板；
- 钱包层、共识层、验证器层不再各自解释协议。

---

### 阶段 1：先做 Sender Receipt 闭环

这是后续最优先的实施阶段，也是当前整个项目最关键的一步。

#### 为什么先做这一阶段

如果 sender 自己都无法完成：

- bundle 提交
- 出块确认
- receipt 回流
- 本地值状态恢复

那么后面的 recipient 收款、P2P 传播、checkpoint 都没有稳定基础。

#### 目标

跑通以下最小链路：

`submit_bundle -> BundlePool -> build/apply block -> generate receipt -> receipt push/pull -> on_receipt_confirmed`

#### 实施方式

新建一条 V2 runtime，不在旧 V1 节点文件里原地改造。

建议新增：

- `EZ_V2/runtime_v2.py`
- `EZ_V2/localnet.py`
- `EZ_V2/services.py`

#### 必做模块

1. `BundleSubmission` 接口层
   - 统一 sender 提交 bundle 的入口；
   - 对接 `BundlePool.submit()`。
2. V2 共识执行器
   - 基于 `ChainStateV2`；
   - 负责打包、生成 `DiffPackage`、应用区块、生成 receipt。
3. Receipt 分发服务
   - winner 主动推送；
   - 落地最近 `R` 块 receipt 缓存；
   - 提供 `GetReceipt(addr, seq)`；
   - 提供 `GetReceiptByRef(BundleRef)`。
4. sender 本地状态推进
   - 收到 receipt 后调用 `on_receipt_confirmed()`；
   - 清除 pending bundle；
   - retained value 恢复可花费。

#### 阶段 1 对共识侧的明确边界

本阶段允许共识执行器以内存态运行，但必须把以下接口和状态语义固定下来：

1. 当前已确认高度；
2. 当前 `block_hash / state_root`；
3. 最近 receipt 查询窗口；
4. sender 的最新 confirmed seq。

也就是说，阶段 1 可以暂不实现“完整共识节点持久化”，但不得把这些状态散落在钱包层或测试脚本里。

#### 公开接口

必须固定为：

- `submit_bundle(submission)`
- `produce_block()`
- `apply_block(block)`
- `get_receipt(addr, seq)`
- `get_receipt_by_ref(bundle_ref)`
- `push_receipt(sender_addr, receipt)`

#### 本阶段不做的事

1. 不做复杂多 leader 竞争；
2. 不做完整 recipient P2P 收款；
3. 不做应用层 UI 细化；
4. 不做 checkpoint 优化策略。

#### 验收标准

1. sender 发送后进入 `PENDING_BUNDLE`；
2. 区块生成后可产出最小 `Receipt`；
3. sender 收到 receipt 后：
   - pending bundle 被移除；
   - retained value 变回 `VERIFIED_SPENDABLE`；
   - outgoing value 进入 `ARCHIVED`；
4. wallet 重启后仍能恢复 pending / receipt / confirmed state；
5. `prev_ref` 连续性可被断言。

---

### 阶段 2：做 Recipient 收款闭环

在 sender receipt 闭环稳定后，再做 recipient 收款。

#### 目标

跑通以下链路：

`export_transfer_package -> send transfer package -> validate transfer -> witness rebase -> receive_transfer`

#### 必做模块

1. `TransferPackage` 传输层
   - 常规路径发送最小必要链；
   - 按 `bundle_hash` 去重；
   - 支持缺失单元按需拉取。
2. recipient 验证服务
   - `V2TransferValidator` 接入实际节点循环；
   - 对 `prev_ref`、递归 witness、state proof、double-spend 做结构化失败返回。
3. recipient 本地落账器
   - 验证通过后执行 witness 重基；
   - 写入本地 `ValueStore`；
   - 新值变为 `VERIFIED_SPENDABLE`。

#### 新消息语义

后续 V2 节点消息固定为：

- `BUNDLE_SUBMIT`
- `RECEIPT_PUSH`
- `GET_RECEIPT`
- `GET_RECEIPT_BY_REF`
- `TRANSFER_PACKAGE`
- `GET_SIDECAR_BY_HASH`

旧消息语义：

- `ACCTXN_SUBMIT`
- `PROOF_TO_SENDER`
- `VPB_TRANSFER`
- `GENESIS_VPB_INIT`

不继续扩展到 V2 主路径。

#### 本阶段不做的事

1. 不做 partial checkpoint；
2. 不做 witness 压缩；
3. 不做复杂异常恢复服务节点。

#### 验收标准

1. recipient 能独立验证并接收 `TransferPackage`；
2. 收到的 witness 被正确重基；
3. recipient 能基于新 witness 再次花费；
4. 缺 receipt、断 `prev_ref`、缺 prior witness、冲突花费等路径会稳定失败。

---

### 阶段 3：建立 V2 Localnet

当 sender 和 recipient 两条闭环都已存在，就应建立真正的 V2 本地网络。

#### 目标

新建一套不依赖 V1 协议对象的 V2 localnet，用于端到端开发和验收。

#### 为什么必须单独建

当前 `run_ez_p2p_network.py` 以及 `modules/ez_p2p/nodes/*` 全部围绕 V1：

- 创世 VPB 初始化
- `SubmitTxInfo`
- `TXPool`
- `Block + Bloom + Merkle`
- `VPB_TRANSFER`

如果在这些文件里原地做双轨语义，复杂度会失控。

#### 必做内容

1. 新建 V2 localnet 启动器
   - 例如 `run_ez_v2_localnet.py` 或 `EZ_V2/localnet.py`。
2. 新建 V2 共识节点循环
   - `BundlePool`
   - `ChainStateV2`
   - `ReceiptCache`
3. 新建 V2 共识状态存储
   - 至少落盘：
     - 已确认 `BlockV2`
     - 最近 receipt 窗口
     - 当前 `height / block_hash / state_root`
     - sender 最新 confirmed seq 或可恢复该状态的最小索引
   - 节点重启后必须可恢复最近确认状态与 receipt 查询能力。
4. 新建 V2 账户节点循环
   - `WalletAccountV2`
   - `LocalWalletDB`
   - `V2TransferValidator`
5. 新建 V2 genesis 初始化
   - 不再生成创世 VPB；
   - 改为 genesis allocation + genesis anchor 初始化。

#### 验收标准

1. 单节点 localnet 可跑通连续多笔交易；
2. 多账户 localnet 能跑通 send/receipt/receive/re-spend；
3. 支持 Carol 式离线后拉取 receipt 恢复；
4. 可复现 `EZchain-V2-small-scale-simulation.md` 的核心场景。
5. 共识节点重启后仍可恢复最近确认状态，并继续提供 receipt 查询。

---

### 阶段 4：把应用层真正切到 V2

此时才能说应用层开始真正接入 V2，而不是“钱包局部接入”。

#### 目标

让 `EZ_App`、CLI、service API 调用的不是“孤立 V2 钱包”，而是“可运行的 V2 runtime / localnet”。

#### 必做内容

1. 扩展 `EZ_App/runtime.py`
   - 现在的 V2 send 只生成 pending bundle；
   - 需要真正调用 V2 runtime 的 `submit_bundle`。
2. 扩展 `service.py`
   - send/balance/history/pending/receipts 都读取 V2 状态；
   - 增加 pending bundles、receipts、checkpoints 查询接口。
3. 扩展 `cli.py`
   - 支持 V2 模式下的 send/balance/history/pending/receipt 查询。
4. 扩展 `NodeManager`
   - 支持启动 V2 localnet；
   - 保留 V1 旧模式，直到 V2 通过稳定性门槛。

#### 公开能力

应用层至少需要暴露：

- `wallet balance`
- `tx send`
- `tx pending`
- `tx receipts`
- `wallet checkpoints`
- `wallet history`

#### 验收标准

1. CLI 不需要人工拼对象即可走通 V2；
2. service API 在 V2 模式下可稳定返回正确状态；
3. 应用层不再需要理解 `VPB_TRANSFER`、`SubmitTxInfo`、Bloom 证明。

---

### 阶段 5：冻结并逐步退役 V1 核心协议路径

只有在 V2 runtime 和 V2 localnet 全部稳定后，才进入这一阶段。

#### 冻结对象

以下 V1 核心对象不再承接新需求：

- `VPBManager`
- `VPBValidator`
- `SubmitTxInfo`
- `TXPool`
- `Blockchain`
- `BlockIndexList`
- `ProofUnit`

#### 退役顺序

1. 先停止新增 V1 功能；
2. 再迁移测试入口；
3. 再切换默认启动入口；
4. 最后保留只读兼容层和历史参考文档。

#### 退役门槛

1. V2 覆盖全部核心交易路径；
2. V2 集成测试覆盖旧 V1 关键场景；
3. V2 的端到端稳定性达到替代要求。

---

## 4. 关键接口与类型的后续固定口径

### 4.1 运行时接口

后续 V2 runtime 对外统一使用以下接口名：

- `submit_bundle(submission)`
- `produce_block()`
- `apply_block(block)`
- `get_receipt(addr, seq)`
- `get_receipt_by_ref(bundle_ref)`
- `export_transfer_package(target_tx, target_value)`
- `receive_transfer(package)`

### 4.2 本地状态

后续钱包公开状态固定为：

- `VERIFIED_SPENDABLE`
- `PENDING_BUNDLE`
- `PENDING_CONFIRMATION`
- `RECEIPT_PENDING`
- `RECEIPT_MISSING`
- `LOCKED_FOR_VERIFICATION`
- `ARCHIVED`

### 4.3 配置项

后续配置层固定增加或保留：

- `app.protocol_version`
- 后续建议增加：
  - `app.runtime_backend`
  - `network.protocol_lane`

用于区分：

- `v1-local`
- `v2-runtime`
- `v2-localnet`

---

## 5. 测试与验收路线

### 5.1 单元测试

持续保留：

1. 编码一致性；
2. 签名与哈希一致性；
3. SMT proof；
4. `prev_ref` 连续性；
5. 递归 witness 验证。

### 5.2 阶段 1 验收测试

必须新增：

1. sender bundle 提交后 receipt 到账；
2. `on_receipt_confirmed()` 后 retained/outgoing 更新正确；
3. wallet 重启后 pending 状态恢复；
4. `GetReceipt(addr, seq)` 和 `GetReceiptByRef` 生效。

### 5.3 阶段 2 验收测试

必须新增：

1. `TransferPackage` 最短链传输；
2. recipient 验证成功并落账；
3. witness 重基后再次花费；
4. 缺 receipt / 缺 sidecar / 断 `prev_ref` 等失败路径。

### 5.4 阶段 3 验收测试

必须新增：

1. 单节点 localnet 端到端；
2. 多账户连续交易；
3. 离线拉取 receipt 恢复；
4. exact-range checkpoint 命中；
5. 复现 `EZchain-V2-small-scale-simulation.md` 的 4 高度核心案例。

### 5.5 替换门槛测试

在默认切换应用层前，必须满足：

1. CLI 端到端走通；
2. service API 走通；
3. 不再依赖 `VPB_TRANSFER`；
4. 不再依赖 Bloom；
5. V2 路径在重启恢复后仍正确。

---

## 6. 当前最该开始做的具体工作

如果只从“下一步应该干什么”来回答，那么答案很明确：

> 先做 `阶段 1：Sender Receipt 闭环`。

原因如下：

1. 这是当前整个项目最核心的系统阻塞点；
2. 它直接决定 `EZ_V2` 是否已经从“协议库”变成“可运行 runtime”；
3. 它会自然拉动：
   - `BundlePool`
   - `ChainStateV2`
   - `ReceiptCache`
   - `WalletAccountV2.on_receipt_confirmed()`
   的真实联动；
4. 做完这一步，后面的 recipient 收款、P2P、CLI、service 才有真实依托。

因此，接下来第一批实现任务应固定为：

1. 新建 `V2 runtime`；
2. 打通 `submit_bundle -> build block -> generate receipt -> get/push receipt`；
3. 在 sender 侧完成 `on_receipt_confirmed()` 闭环；
4. 为该闭环建立单节点集成测试。

---

## 7. 一句话结论

`EZ_V2` 当前已经不是“没有核心代码”，而是“没有进入项目主循环”。

后续最正确的做法不是继续在外围补接口，而是：

> 先把 `EZ_V2` 建成一条独立可运行的 runtime / localnet 路线，先跑通 sender receipt，再跑通 recipient 收款，再切应用层，最后冻结 V1。

这是当前仓库现实下，风险最低、返工最少、最有机会真正把 V2 落地成项目的路径。
