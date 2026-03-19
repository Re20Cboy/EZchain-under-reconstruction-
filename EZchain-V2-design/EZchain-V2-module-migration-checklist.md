# EZchain-V2 模块级迁移清单

## 0. 文档目的

本清单基于当前 `EZchain-V1` 本地代码实现整理，目标是回答两个工程问题：

1. 哪些 V1 模块可以直接继承到 V2；
2. 哪些 V1 模块只能继承“存储/索引思想”，但对象模型必须重写。

本文将模块分为三类：

- `A. 可基本继承`：核心思想和代码形态都可延续，仅需小幅改名或补字段。
- `B. 保留架构模式，重写对象语义`：存储方式、索引方式、缓存方式值得保留，但协议对象已经变化，不能原样照搬。
- `C. 必须重写`：V1 与 V2 的协议锚点和验证语义已明显不同，强行复用会把 Bloom/旧 witness 逻辑带入 V2。

---

## 1. 总体结论

`EZchain-V1` 最值得继承的，不是 `ProofUnit / BlockIndex / Bloom` 本身，而是以下工程方法：

- 使用 SQLite 做轻量级本地持久化；
- 将“大对象”和“映射关系”分开存储，避免重复写盘；
- 为同一条历史链维护顺序字段，支持快速恢复；
- 使用本地缓存加速热点读取；
- 以 `Account` 为统一编排入口，把 Value、Witness、Checkpoint、验证器封装起来。

V2 真正应该继承的是这些方法；真正应该替换的是旧协议对象。

---

## 2. A 类：可基本继承

### 2.1 签名与规范编码辅助

- 模块：
  - `EZ_Tool_Box/SecureSignature.py`
  - `modules/ez_p2p/security.py`
  - `modules/ez_p2p/codec/json_codec.py`
- 迁移结论：`基本继承`
- 原因：
  - V1 已经有“规范 JSON + sort_keys + separators”的确定性签名输入思路；
  - `ez_p2p` 模块已经使用 JSON 编码而不是 `pickle`；
  - 这些模块与 Bloom/VPB 语义耦合较低。
- V2 落地动作：
  - 新增 `sign_bundle_envelope()` / `verify_bundle_envelope()`；
  - 新增 `ReceiptResponse`、`TransferPackage` 的规范编码函数；
  - 在签名域中补齐 `chain_id`、`version`、`expiry_height`、`seq`。
- 注意事项：
  - 不要复用旧的交易字段名集合，V2 应以 `BundleEnvelope` 为签名主体；
  - 调试日志中的敏感信息输出需要收敛。

### 2.2 Value 区间对象

- 模块：
  - `EZ_VPB/values/Value.py`
- 迁移结论：`基本继承`
- 原因：
  - `begin_index + value_num + end_index` 的区间表示仍是 EZchain 的核心；
  - `split_value()`、区间相交判断、包含判断在 V2 仍然需要。
- V2 落地动作：
  - 保留区间数学逻辑；
  - 仅调整状态枚举，使其对齐 V2 的 `SPENDABLE / PENDING_BUNDLE / RECEIPT_MISSING / LOCKED_FOR_VERIFICATION / ARCHIVED`。
- 注意事项：
  - `Value` 在 V2 中应继续保持“纯区间对象”定位，不要把 witness 数据混入 `Value` 本体。

---

## 3. B 类：保留架构模式，重写对象语义

### 3.1 本地 Value 存储层

- 模块：
  - `EZ_VPB/values/AccountValueCollection.py`
- 迁移结论：`保留模式，重写字段与状态语义`
- V1 可继承点：
  - 本地 SQLite 存储；
  - `account_address + node_id` 维度管理；
  - 顺序字段 `sequence`；
  - 热点缓存与状态索引。
- V2 对应目标：
  - `ValueStore`
  - `LocalValueRecord`
- 必改内容：
  - 状态机从 V1 的 `UNSPENT/PENDING/ONCHAIN/VERIFIED/...` 改为 V2 状态；
  - `node_id` 只能是本地对象标识，不能再承担协议锚点语义；
  - 需要增加 `latest_receipt_ref`、`witness_status`、`sidecar_retention_state` 等本地元数据。
- 建议：
  - 保留表驱动存储思路；
  - 将 V2 的 witness 元数据从 `value_data` 中拆出，避免单表过胖。

### 3.2 选值器

- 模块：
  - `EZ_VPB/values/AccountPickValues.py`
- 迁移结论：`保留框架，重写选值策略`
- V1 可继承点：
  - 在本地 Value 集上做选择；
  - 以 checkpoint 辅助优先级；
  - 找零/分裂逻辑的工程入口已经具备。
- V2 对应目标：
  - `ValueSelectorV2`
- 必改内容：
  - 选值时必须排除 `RECEIPT_MISSING`、`LOCKED_FOR_VERIFICATION`；
  - 优先选择 witness 较短、checkpoint 较近的值；
  - split 后的 witness 继承规则必须与协议草案一致。

### 3.3 Checkpoint 存储层

- 模块：
  - `EZ_CheckPoint/CheckPoint.py`
- 迁移结论：`保留 upsert/cache 模式，扩展记录语义`
- V1 可继承点：
  - `CheckPointRecord` 的本地持久化；
  - 以 `(value_begin_index, value_num)` 为键的精确匹配；
  - 热点缓存；
  - 按 owner、高度查询。
- V2 对应目标：
  - `CheckpointStore`
  - `CheckpointRecordV2`
- 必改内容：
  - 记录至少补齐 `block_hash`、`bundle_hash` 或 `bundle_ref`；
  - 在 V2 第一版中仅允许 `exact-range checkpoint`；
  - Checkpoint 不能再只绑定高度。

### 3.4 Witness 对象池与映射层

- 模块：
  - `EZ_VPB/proofs/AccountProofManager.py`
  - `EZ_VPB/proofs/Proofs.py`
- 迁移结论：`强烈建议保留“共享对象池 + 映射表 + sequence”模式，但对象必须重写`
- V1 可继承点：
  - 唯一对象表；
  - `Value -> Object` 映射表；
  - `sequence` 保序；
  - 本地去重缓存；
  - 按账户/值快速恢复完整历史链。
- V2 对应目标：
  - `ConfirmedUnitStore`
  - `BundleSidecarStore`
  - `ValueConfirmedUnitMapping`
- 必改内容：
  - `ProofUnit` 改为 `ConfirmedBundleUnit`；
  - 额外拆出 `bundle_hash -> BundleSidecar` 的对象池；
  - `Receipt` 和 `BundleSidecar` 不应再塞进单一旧 proof 表结构。
- 必修正问题：
  - 旧 `ProofUnit.unit_id` 不是稳定确定性 ID；
  - 旧 `reference_count` 逻辑会在重复映射时被错误累加；
  - 旧接口里 `LegacyProofsStorage` 与新接口并存，V2 必须收敛成单一路径。

### 3.5 链式索引与本地历史检索层

- 模块：
  - `EZ_VPB/block_index/AccountBlockIndexManager.py`
  - `EZ_VPB/block_index/BlockIndexList.py`
- 迁移结论：`保留存储/缓存/merge 机制，重写对象语义`
- V1 可继承点：
  - 每个 value 单独维护链式索引；
  - SQLite + 内存缓存；
  - merge 更新；
  - 适合消费级设备的增量追加。
- V2 对应目标：
  - `ReceiptRefIndex`
  - `PriorWitnessLinkStore`
- 必改内容：
  - 旧 `index_lst` 不再记录“Bloom 命中的高度列表”；
  - 新索引应记录 `bundle_ref`、`prev_ref`、`HeaderLite` 或其他最小确认锚点；
  - 验证逻辑不能再调用 `is_in_bloom()`。

### 3.6 Account 总编排层

- 模块：
  - `EZ_Account/Account.py`
- 迁移结论：`保留“统一入口”思路，重写操作语义`
- V1 可继承点：
  - 一个 `Account` 统一协调 Value、Witness、Checkpoint、验证器；
  - sender 更新、receiver 接收、checkpoint 更新都有清晰入口。
- V2 对应目标：
  - `WalletAccountV2`
- 必改内容：
  - `update_vpb_after_transaction_sent()` 应改为 `on_receipt_confirmed()`；
  - `receive_vpb_from_others()` 应改为 `receive_transfer_package()`；
  - 本地状态推进改成围绕 `Receipt` 和 `WitnessV2`。

---

## 4. C 类：必须重写

### 4.1 主链与区块结构

- 模块：
  - `EZ_Main_Chain/Block.py`
  - `EZ_Main_Chain/Blockchain.py`
- 迁移结论：`必须重写`
- 原因：
  - V1 的区块结构围绕 `Bloom + m_tree_root`；
  - V2 需要 `state_root + diff_root + DiffPackage`；
  - 当前实现还含有 `pickle` 序列化路径。
- V2 对应目标：
  - `BlockHeaderV2`
  - `BlockBodyV2`
  - `StateTreeApplier`

### 4.2 交易提交与交易池

- 模块：
  - `EZ_Transaction/MultiTransactions.py`
  - `EZ_Transaction/SubmitTxInfo.py`
  - `EZ_Tx_Pool/TXPool.py`
- 迁移结论：`必须重写`
- 原因：
  - V2 的主提交对象已经从 `MultiTransactions + SubmitTxInfo` 变成 `BundleEnvelope + BundleSidecar`；
  - 当前编码和验证仍有 `pickle` 依赖；
  - mempool 索引也应改成 `sender + seq`。
- V2 对应目标：
  - `BundleEnvelope`
  - `BundleSidecar`
  - `BundlePool`

### 4.3 旧 VPB 证明对象

- 模块：
  - `EZ_VPB/proofs/ProofUnit.py`
  - `EZ_VPB/proofs/Proofs.py`
- 迁移结论：`必须重写`
- 原因：
  - V2 的确认对象已经不是“某区块中 sender 的 `ProofUnit`”，而是“最小 Receipt + 本地 Sidecar 还原出的 `ConfirmedBundleUnit`”。

### 4.4 旧 BlockIndex 验证逻辑

- 模块：
  - `EZ_VPB/block_index/BlockIndexList.py`
- 迁移结论：`必须重写`
- 原因：
  - `verify_index_list()` 强耦合 Bloom；
  - 高度索引不足以表达 V2 的 `bundle_ref / prev_ref` 关系。

### 4.5 验证器

- 模块：
  - `EZ_VPB_Validator/`
- 迁移结论：`必须重写`
- 原因：
  - V1 验证器的核心输入是 `VPB + Bloom + Merkle root`；
  - V2 需要验证 `Receipt + state_root + account_state_proof + 递归 witness`。

### 4.6 Merkle 证明结构

- 模块：
  - `EZ_Units/MerkleProof.py`
- 迁移结论：`必须重写`
- 原因：
  - V1 的 proof 结构是普通 Merkle 树路径，并通过“两种拼接顺序都尝试”验证；
  - V2 的 SMT proof 需要显式方向位、固定深度语义或压缩位图语义。

---

## 5. 存储表迁移建议

V2 推荐延续 V1 的 SQLite 设计，但表语义需要换血。

### 5.1 可沿用思路的旧表

- `value_data`
  - V2 可演进为 `value_records`
- `account_value_proofs`
  - V2 可演进为 `value_confirmed_units`
- `proof_units`
  - V2 可拆成 `confirmed_bundle_units` 与 `bundle_sidecars`
- `block_indices`
  - V2 可演进为 `value_receipt_refs`
- `checkpoints`
  - V2 可演进为 `checkpoints_v2`

### 5.2 推荐的新表结构方向

- `value_records`
  - 每条 Value/ValueRange 的本地状态
- `bundle_sidecars`
  - 按 `bundle_hash` 去重存储 Bundle 内容
- `receipts`
  - 按 `bundle_ref` 或 `(addr, seq)` 存储最小 Receipt
- `confirmed_bundle_units`
  - `Receipt + bundle_hash` 组合出的确认单元
- `value_confirmed_units`
  - `value_id -> confirmed_unit_id` 的有序映射
- `value_receipt_refs`
  - 每个 Value 当前 witness 链的快速定位索引
- `checkpoints_v2`
  - 绑定 `value_range + owner + block_hash + bundle_ref`

---

## 6. 迁移红线

以下内容在 V2 中不得原样继承：

1. 任何 `pickle` 参与的网络消息、签名输入、跨节点对象交换。
2. 任何基于 Bloom 的历史索引合法性验证。
3. 任何非确定性对象 ID 生成方式。
4. 任何“先增引用，再检查映射是否已存在”的引用计数更新逻辑。
5. 旧 `ProofUnit` 语义本体。

---

## 7. 推荐实施顺序

1. 先保留 V1 的 `ValueStore / CheckpointStore / 本地缓存` 思路。
2. 重写 `BundleEnvelope / BundleSidecar / BundlePool`。
3. 新建 `Receipt / ConfirmedBundleUnit / WitnessV2` 的对象池与映射层。
4. 新建 SMT 与 `account_state_proof` 验证。
5. 重写 `Account` 编排层与 V2 验证器。
6. 最后再替换旧主链结构与出块/验块流程。

---

## 8. 一句话结论

V1 最值得继承的是“轻量本地数据库工程化方法”；  
V2 最必须重写的是“链上锚点对象与验证语义”。
