# EZchain-V2 协议规范草案（Draft v0.2）

## 0. 文档定位

本文档是面向 EZchain-V2 正式工程落地的协议规范草案。

它的目标不是仅描述一个“想法”，而是尽可能把以下内容写成可以直接指导实现、测试与安全审计的协议级规格：

- 链上数据结构
- 链下 Witness 数据结构
- Bundle 提交、打包、广播、验块流程
- Receipt 生成与拉取流程
- 用户侧 P2P 验证流程
- Checkpoint 触发与更新流程
- 异常、失败语义与攻击面

本文档明确采用以下路线：

- 保留“单状态树根”路线，不采用双状态根
- 采用 `Sparse Merkle Tree`（SMT）作为全局账户状态树
- 采用 `diff_root` 作为区块辅助承诺
- 引入 `claim_set_hash`，作为 `AccountLeaf` 中的定长 Value 集承诺
- 不引入 `source_ref`
- 继续保持 EZchain 的核心理念：共识层只做轻验证与状态承诺，Value 合法性主要由链下用户节点在 P2P 阶段完成

本文档中使用规范性术语：

- `MUST`：必须满足
- `SHOULD`：强烈建议满足，除非有明确理由不满足
- `MAY`：可选

---

## 1. 设计目标与非目标

### 1.1 设计目标

EZchain-V2 的目标是：

1. 去除 V1 中主链 Bloom filter 的存储与假阳性问题。
2. 保留 VWchain/EZchain 的“链下自主验证、链上轻承诺”哲学。
3. 使共识节点能够仅凭：
   - 上一状态树根
   - 本块变更集
   - Bundle 签名与基础合法性
   完成新区块验证。
4. 使用户节点能够仅凭：
   - 自己长期保存的 V-W 数据
   - 对方提供的 Receipt / Witness
   - 少量主链头信息
   完成交易安全验证。
5. 在分叉环境下保持安全，避免仅用区块高度造成歧义。
6. 在用户离线、漏领 Receipt、短时失联等情况下给出清晰失败语义和恢复路径。

### 1.2 非目标

EZchain-V2 当前草案不追求：

1. 让共识节点验证每个 Value 的合法花销。
2. 让主链完整承诺每个 Value 的输入集合。
3. 让任意节点永久为任意历史块提供完整 Receipt 重建服务。
4. 在协议第一版中引入 Verkle tree、ZKP 或复杂数据可用性编码。

### 1.3 轻量设备约束

EZchain-V2 的目标部署环境包含消费级设备、个人设备与轻量终端，因此协议设计必须额外满足以下约束：

1. 凡是用户节点本地已经确定持有的数据，共识节点 SHOULD NOT 再重复回传。
2. 凡是可由本地数据和少量链上证明重建的字段，Receipt MUST 尽量不重复携带。
3. 用户节点长期保存的链上确认信息 SHOULD 压缩到最小集合，优先保存 `height + block_hash + state_root` 这类必要承诺。
4. Witness 与本地缓存 SHOULD 支持按 `bundle_hash` 去重，避免同一 Bundle 内容在多个 Value 记录中重复存储。

---

## 2. 系统模型与威胁模型

### 2.1 节点类型

网络中存在两类节点：

1. 共识节点（Consensus Node）
2. 用户节点（Account Node / User Node）

### 2.2 网络模型

- 共识节点网络为半同步网络。
- 用户节点可频繁离线、重连、切换网络环境。
- 用户节点之间存在点对点通信能力，用于传输 Value-Witness 数据。

### 2.3 安全假设

1. 底层共识协议可保证已确认区块头不可篡改。
2. 哈希函数满足抗碰撞性。
3. secp256k1 签名不可伪造。
4. 诚实用户在接受交易前，会先执行完整 Witness 验证，而不是“先收款、后验证”。

### 2.4 攻击者能力

攻击者可以：

- 控制部分共识节点
- 控制部分用户节点
- 构造恶意 Bundle
- 隐瞒自身 Witness 数据
- 在 P2P 阶段对不同用户发送不同的链下消息
- 伪装离线、拒绝提供历史 Receipt

攻击者不能：

- 伪造有效签名
- 篡改已确认区块头中的 `state_root`、`diff_root`
- 对哈希函数找到碰撞

---

## 3. V2 的核心思想

V2 的核心变化不是引入一套新的链上 Value 来源索引，而是把 V1 中用于发现 sender 历史提交位置的 Bloom filter，替换为由账户状态树维护的精确 sender 历史入口。

V1 中用户验证依赖两类链上辅助信息：

- `Bloom filter`：发现某 sender 在哪些区块提交过交易
- `Merkle proof`：证明某个 Bundle 确实上链

V2 则改造为：

- `Account state SMT`：记录每个地址最新一次与上一次已确认 Bundle 引用
- `diff_root`：承诺本块全部状态变更的确定性结果
- `Receipt`：证明某地址某次 Bundle 对应的最新叶子已被纳入该块 `state_root`
- `prev_ref` 链：保证同一 sender 自身提交历史的连续性
- `WitnessV2`：以“当前 sender 证明段 + 前序 Witness 递归锚点”的方式保存 Value 历史

这意味着：

1. V2 可以精确发现“某 sender 在历史上到底提交过哪些 Bundle”，不再依赖 Bloom。
2. 共识层只负责验证 sender 的 Bundle 提交事件、状态叶子更新和 diff 的确定性，不直接验证每个 Value 的来源。
3. Value 的来源合法性仍然由用户节点在 P2P 阶段完成，但验证方式改为：从当前 sender 开始，沿着递归 Witness 逐段回溯，每一段内部再通过 `prev_ref` 链验证该 sender 没有隐瞒自己的历史 Bundle。

这是 V2 最关键的协议结论：

> V2 并没有取消 Value-Witness，只是把 V1 中 Bloom-based sender activity index，替换成了 state-root + receipt + prev_ref 的精确 sender 历史索引。

---

## 4. 密码学原语与规范编码

### 4.1 哈希函数

默认采用：

- `Keccak256`

所有哈希对象 MUST 带域分离前缀。

### 4.2 签名算法

默认采用：

- `secp256k1 recoverable ECDSA`

签名 MUST 满足：

- 带 `chain_id`
- 带 `domain_separator`
- 强制 `low-s`

### 4.3 编码规则

所有被哈希、被签名、被作为 Merkle 叶子输入的数据 MUST 采用规范二进制编码。

协议层禁止：

- 直接对 JSON 签名
- 不带字段顺序约束的自由序列化
- 使用 `pickle` 作为网络协议编码

MVP 版本可采用一种固定字段顺序、固定整数大小、长度前缀明确的编码方案，以下简称：

- `canonical_encode(x)`

本文档不强制指定 RLP/SSZ/自定义 TLV，但实现必须做到：

1. 字段顺序固定
2. 整数编码固定
3. 列表顺序固定
4. 相同语义对象编码结果唯一

---

## 5. 基础对象定义

### 5.1 BundleRef

`BundleRef` 是 V2 中唯一定位某次 sender 提交事件的引用。

```text
BundleRef {
  height: uint64
  block_hash: bytes32
  bundle_hash: bytes32
  seq: uint64
}
```

其中：

- `height`：区块高度
- `block_hash`：该区块头哈希
- `bundle_hash`：Bundle sidecar 的哈希
- `seq`：sender 的已确认顺序号

`BundleRef` 必须作为一个整体比较，不允许仅以 `height` 判等。

对任意 `ConfirmedBundleUnit U`，定义：

```text
confirmed_ref(U) = BundleRef {
  height = U.receipt.header_lite.height
  block_hash = U.receipt.header_lite.block_hash
  bundle_hash = Keccak256("EZCHAIN_BUNDLE_BODY_V2" || canonical_encode(U.bundle_sidecar))
  seq = U.receipt.seq
}
```

### 5.2 OffChainTx

V2 仍允许一个 Bundle 内包含多笔子交易，但不对每笔子交易单独签名。

```text
OffChainTx {
  sender_addr
  recipient_addr
  value_list
  tx_local_index
  tx_time
  extra_data
}
```

说明：

- `value_list` 是一组 Value 区间
- `tx_local_index` 仅用于 Bundle 内唯一定位
- 子交易的合法性由 Bundle 总签名背书

### 5.3 BundleEnvelope

```text
BundleEnvelope {
  version
  chain_id
  seq
  expiry_height
  fee
  bundle_hash
  claim_set_hash
  anti_spam_nonce
  sig
}
```

签名摘要：

```text
SigHash = Keccak256(
  "EZCHAIN_BUNDLE_V2" ||
  canonical_encode(
    version,
    chain_id,
    seq,
    expiry_height,
    fee,
    bundle_hash,
    claim_set_hash,
    anti_spam_nonce
  )
)
```

### 5.4 BundleSidecar

```text
BundleSidecar {
  sender_addr
  tx_count
  tx_list: [OffChainTx]
}
```

约束：

1. `sender_addr` MUST 与 `BundleEnvelope` 恢复出的地址一致。
2. `bundle_hash = Keccak256("EZCHAIN_BUNDLE_BODY_V2" || canonical_encode(BundleSidecar))`
3. Bundle 内所有 `OffChainTx.sender_addr` MUST 等于 `BundleSidecar.sender_addr`

### 5.5 AccountLeaf

SMT 叶子保存的是某地址最近一次与上一次已确认 Bundle 的引用。

```text
AccountLeaf {
  addr
  head_ref: BundleRef | NULL
  prev_ref: BundleRef | NULL
  claim_set_hash: bytes32 | NULL
}
```

哈希：

```text
leaf_hash = Keccak256("EZCHAIN_ACCOUNT_LEAF_V2" || canonical_encode(AccountLeaf))
```

解释：

- `head_ref`：该地址最新一次已确认 Bundle
- `prev_ref`：该地址次新一次已确认 Bundle
- `claim_set_hash`：`head_ref` 对应 Bundle 的 Value 集合定长摘要承诺；当地址尚无已确认 Bundle 时为 `NULL`

当某地址首次上链时：

- `old_leaf = NULL`
- `new_leaf.head_ref = current_ref`
- `new_leaf.prev_ref = NULL`

当某地址再次上链时：

- `new_leaf.head_ref = current_ref`
- `new_leaf.prev_ref = old_leaf.head_ref`

### 5.6 DiffEntry

```text
DiffEntry {
  addr_key
  new_leaf
  bundle_envelope
  bundle_hash
}
```

其中：

- `addr_key = Keccak256("EZCHAIN_ADDR_KEY_V2" || addr)`

注意：

- `DiffEntry` 不直接携带 `BundleSidecar`，但它承诺 `bundle_hash`
- 验块时必须同时拿到真实 `BundleSidecar`

`DiffLeafHash` 定义为：

```text
DiffLeafHash = Keccak256(
  "EZCHAIN_DIFF_LEAF_V2" ||
  canonical_encode(
    addr_key,
    Keccak256(canonical_encode(new_leaf)),
    Keccak256(canonical_encode(bundle_envelope)),
    bundle_hash
  )
)
```

### 5.7 HeaderLite

用户侧长期保存的头信息不需要完整 `BlockHeader`，只需要最小确认承诺：

```text
HeaderLite {
  height
  block_hash
  state_root
}
```

### 5.8 Receipt

Receipt 是共识节点下发给 sender 的“最小链上确认回执”，只携带用户本地无法自行得知的链上确认信息。

```text
Receipt {
  header_lite
  seq
  prev_ref
  account_state_proof
}
```

其中：

- `header_lite.height`：本次 Bundle 被确认的区块高度
- `header_lite.block_hash`：该区块哈希
- `header_lite.state_root`：该区块执行后的状态树根
- `seq`：该 sender 本次已确认 Bundle 的顺序号
- `prev_ref`：该 sender 上一次已确认 Bundle 引用
- `account_state_proof`：证明该 sender 新叶子位于 `state_root` 下的 SMT 路径

Receipt 不包含：

- 完整 `BlockHeader`
- `BundleEnvelope`
- `BundleSidecar`
- 完整 `AccountLeaf` 负载

原因是：

1. `BundleEnvelope / BundleSidecar` 原本就是 sender 本地提交的数据，不应由共识节点重复回传。
2. `AccountLeaf` 不是由裸 `sender_addr + seq + prev_ref + HeaderLite` 重建，而是必须由 `bundle_sidecar` 先计算 `bundle_hash`，再与 `sender_addr + prev_ref + HeaderLite(height, block_hash) + seq` 一起重建；否则链上证明将无法绑定具体 Bundle 内容。
3. 由于协议引入 `claim_set_hash`，它必须由 `BundleSidecar` 重算并进入重建出的 `AccountLeaf`；否则 recipient 无法确认该摘要确实被 `state_root` 承诺。
4. 轻量设备长期保存 `HeaderLite` 的成本显著低于完整区块头。

### 5.9 ConfirmedBundleUnit

用户侧进行链下验证时，真正使用的不是孤立的 Receipt，而是“Receipt + 对应 Bundle 内容”的组合单元：

```text
ConfirmedBundleUnit {
  receipt
  bundle_sidecar
}
```

验证者据此可重建：

```text
reconstructed_leaf(U) = AccountLeaf {
  addr = U.bundle_sidecar.sender_addr
  head_ref = confirmed_ref(U)
  prev_ref = U.receipt.prev_ref
  claim_set_hash = compute_claim_set_hash(U.bundle_sidecar)
}
```

因此，`ConfirmedBundleUnit` 才是 P2P 验证中的最小自包含单元，而 `Receipt` 只是其中的链上确认部分。

### 5.10 WitnessV2

V2 中，单个 Value 或 ValueRange 的 Witness 采用递归结构，而不是额外引入新的链上索引对象。

```text
WitnessV2 {
  value
  current_owner_addr
  confirmed_bundle_chain: [ConfirmedBundleUnit]
  anchor
}
```

其中：

```text
WitnessAnchor =
  GenesisAnchor
  | CheckpointAnchor
  | PriorWitnessLink

GenesisAnchor {
  genesis_block_hash
  first_owner_addr
  value_begin
  value_end
}

CheckpointAnchor {
  checkpoint
}

PriorWitnessLink {
  acquire_tx
  prior_witness: WitnessV2
}
```

解释：

- `confirmed_bundle_chain` 表示“当前 owner 自最近一次获得该 Value 以来，到当前最新一次已确认 Bundle 为止”的本地提交历史。
- `confirmed_bundle_chain` 内部按时间从新到旧排序，并且必须能通过 `prev_ref` 连续连接。
- `confirmed_bundle_chain` MAY 为空；这表示当前 owner 已经获得该 Value，但自获得以来尚未有任何已确认 Bundle。
- `anchor` 用来说明这段 sender 历史之前的来源锚点。
- 若 `anchor = GenesisAnchor`，表示该 Value 的递归验证到创世分配处终止。
- 若 `anchor = CheckpointAnchor`，表示该 Value 的递归验证可以在本地可信检查点终止。
- 若 `anchor = PriorWitnessLink`，表示该 Value 是由前序 sender 通过 `acquire_tx` 转入当前 owner，验证者必须继续递归验证 `prior_witness`。

这里不引入 `source_ref`。`acquire_tx` 只是用户侧 Witness 中随附的实际转移交易对象，最终仍需由接收者在 `prior_witness` 对应的 Bundle 数据中自行核验其真实性。

### 5.11 Checkpoint

```text
Checkpoint {
  value_begin
  value_end
  owner_addr
  checkpoint_height
  checkpoint_block_hash
  checkpoint_bundle_hash
}
```

Checkpoint 仅是用户侧优化对象，不是主链共识状态。

Checkpoint 的使用边界必须保持“纯用户侧、本地可决定”：

- sender MUST 根据自己已持有的完整 witness / value history，本地决定是否可以对某个 recipient 使用 exact-range checkpoint 裁剪。
- sender MUST NOT 为了决定 witness 截断位置，再向 recipient 额外发起一次“你有没有 checkpoint / checkpoint 在哪里”的协商或发现请求。
- recipient MUST 使用自己的本地 checkpoint 与本地历史记录验证 `CheckpointAnchor`；checkpoint 命中是本地验证问题，不应引入新的发送前往返通信。
- 若当前 value 不能被 sender 在本地明确裁剪到 exact-range checkpoint，则 sender MUST 回退为发送足够的完整 prior witness，而不是引入额外协议交互。

---

## 6. 全局状态树

### 6.1 树类型

V2 MUST 使用固定叶位的 `Sparse Merkle Tree`。

键：

- `addr_key = Keccak256("EZCHAIN_ADDR_KEY_V2" || addr)`

值：

- `leaf_hash`

### 6.2 为什么必须是 SMT

如果使用普通动态 Merkle 列表，则：

1. 地址集合变化会导致叶子位置变化
2. “部分更新”将失去确定性
3. proposer 给不同验证者发送不同的叶子排序，可能导致网络恢复出不同根

SMT 的优势是：

1. 地址位置固定
2. 单地址更新总是沿固定路径发生
3. 任意共识节点都能从相同旧根和相同 diff 重算出相同新根

### 6.3 历史版本

共识节点运行时至少维护：

1. 当前最新 `state_root`
2. 生成本块所需的上一版本叶子信息

协议不强制所有节点永久保存全部历史版本树。

但 winner 在块确认时 MUST 为本块所有变更 sender 生成 Receipt，并将其下发或缓存。

---

## 7. 区块结构

### 7.1 BlockHeader

```text
BlockHeader {
  version
  chain_id
  height
  prev_block_hash
  state_root
  diff_root
  timestamp
  proposer_sig
  consensus_extra
}
```

说明：

- `state_root`：本块执行后的全局账户状态树根
- `diff_root`：本块变更集承诺
- `diff_root` 不是第二棵状态树根，只是辅助承诺

### 7.2 DiffPackage

```text
DiffPackage {
  diff_entries: [DiffEntry]          // 按 addr_key 严格排序
  sidecars: [BundleSidecar]          // 与 diff_entries 一一对应
}
```

约束：

1. `diff_entries` MUST 按 `addr_key` 升序排序。
2. 不允许重复 `addr_key`。
3. `len(diff_entries) == len(sidecars)`。
4. `sidecars[i]` 的 `bundle_hash` 必须等于 `diff_entries[i].bundle_hash`。

### 7.3 diff_root 计算

```text
diff_root = MerkleRoot([DiffLeafHash_1, DiffLeafHash_2, ..., DiffLeafHash_n])
```

其中 Merkle 叶的顺序由 `addr_key` 升序确定。

---

## 8. Mempool 规则

### 8.1 核心原则

V2 继续坚持：

> 每块每 sender 至多一个 Bundle

这是协议级安全约束，不只是性能优化。

### 8.2 接入校验

共识节点收到 `BundleEnvelope + BundleSidecar` 后 MUST 执行：

1. 恢复 sender 地址
2. 验证 `hash(sidecar) == bundle_hash`
3. 验证 `compute_claim_set_hash(sidecar) == claim_set_hash`
4. 验证 `sender_addr == sidecar.sender_addr`
5. 验证 `chain_id`
6. 验证 `expiry_height`
7. 验证 `low-s`
8. 验证 `seq`
9. 验证大小限制
10. 验证 `BundleSidecar` 内所有 tx 的 sender 一致

### 8.3 seq 规则

记链上已确认叶子中的最新 seq 为 `confirmed_seq`。

则：

- 可执行 Bundle 的 `seq` 必须等于 `confirmed_seq + 1`

MVP 版本建议：

1. 同一 sender 仅保留一个“待执行 Bundle”
2. 若新 Bundle 的 `seq` 不等于当前可执行 seq，则拒绝
3. 若同一 sender 已有待执行 Bundle：
   - 默认拒绝新的不同 `seq`
   - MAY 支持“同 seq 且更高手续费”的替换

### 8.4 大小限制

为避免链下验证 DoS，协议 SHOULD 设置：

- `MAX_BUNDLE_BYTES`
- `MAX_TX_PER_BUNDLE`
- `MAX_VALUE_ENTRIES_PER_TX`

即使 V2 引入 `claim_set_hash`，recipient 在正例命中时仍需扫描 Bundle 内容做最终冲突检查，故大小限制依然非常重要。

---

## 9. 出块算法

### 9.1 输入

输入：

- 上一块 `state_root`
- 本地 mempool
- 本地最新状态树

输出：

- `BlockHeader`
- `DiffPackage`

### 9.2 出块步骤

1. 从 mempool 选择一组合法 Bundle。
2. 按 sender 去重，确保每 sender 最多一个 Bundle。
3. 对每个 sender：
   - 查询旧叶子 `old_leaf`
   - 构造 `current_ref`
   - 生成 `new_leaf`
4. 构造 `DiffEntry` 列表并按 `addr_key` 排序。
5. 计算 `diff_root`。
6. 将所有 `new_leaf` 应用到本地 SMT，得到 `state_root`。
7. 结合前序块哈希、时间戳、共识信息生成 `BlockHeader`。
8. 广播 `BlockHeader + DiffPackage`。

### 9.3 new_leaf 构造规则

若 `old_leaf = NULL`：

```text
new_leaf.head_ref = current_ref
new_leaf.prev_ref = NULL
```

若 `old_leaf != NULL`：

```text
new_leaf.head_ref = current_ref
new_leaf.prev_ref = old_leaf.head_ref
```

### 9.4 为什么只需要两跳引用

`AccountLeaf` 只保存最近两跳引用，但历史不会丢失，因为：

1. 每个历史块的 Receipt 都保存了当时 sender 的 `prev_ref`
2. 历史 `ConfirmedBundleUnit` 可由 `Receipt + BundleSidecar` 重建当时的 `AccountLeaf`
3. 历史 Receipt 中的 `prev_ref` 会形成不可篡改的倒链

因此：

- 链上状态树只需要保存最新状态
- 历史链由 Receipt 持久化

---

## 10. 验块算法

### 10.1 共识节点必须验证的内容

共识节点收到 `BlockHeader + DiffPackage` 后 MUST 验证：

1. 区块头基础合法性
2. proposer 签名
3. `diff_entries` 排序和去重正确
4. 每个 `bundle_hash == hash(sidecar)`
5. `bundle_envelope` 签名合法
6. `BundleSidecar.sender == recovered_sender`
7. 每 sender 在本块中只出现一次
8. `seq` 合法
9. `new_leaf` 构造合法
10. 根据上一状态树应用变更后得到的根等于 `state_root`
11. 由 `diff_entries` 计算出的 Merkle 根等于 `diff_root`

### 10.2 new_leaf 合法性检查

对每个 sender：

1. 从旧状态树读取 `old_leaf`
2. 检查 `new_leaf.addr == sender_addr`
3. 检查 `new_leaf.head_ref.bundle_hash == diff_entry.bundle_hash`
4. 若 `old_leaf = NULL`：
   - `new_leaf.prev_ref MUST = NULL`
   - `bundle.seq MUST = 1` 或等于协议定义的起始 seq
5. 若 `old_leaf != NULL`：
   - `new_leaf.prev_ref MUST = old_leaf.head_ref`
   - `bundle.seq MUST = old_leaf.head_ref.seq + 1`

### 10.3 注意事项

共识节点不验证：

- Value 是否真实未双花
- Value 来源是否合法
- tx 内 value 区间是否与其他 sender 的 value 冲突

这些仍由用户侧 P2P 验证负责。

---

## 11. Receipt 生成与分发

### 11.1 Receipt 生成时机

winner 在区块被本地接受后，MUST 为本块每个变更 sender 生成 Receipt。

若底层共识只有概率确认，则：

- Receipt 可立即生成
- 但用户在 P2P 验证时 SHOULD 只使用已确认深度足够的 Receipt

### 11.2 Receipt 内容

Receipt 不要求自包含 Bundle 内容。它的定位是：

> 只承载“用户本地无法自行得知”的链上确认信息。

Receipt 至少包含：

1. `HeaderLite`
2. `seq`
3. `prev_ref`
4. `account_state_proof`

sender 在验证 Receipt 时，应使用自己本地保存的 `BundleSidecar` 重建 `ConfirmedBundleUnit`，而不是要求共识节点把 `BundleEnvelope`、`BundleSidecar` 再发回一次。

### 11.3 Receipt 分发策略

建议采用：

- 推送优先，拉取兜底

流程：

1. winner 主动向 sender 推送最小 Receipt
2. 若 sender 离线，则写入“最近 Receipt 缓存”
3. sender 日后可向任意共识节点发起 `GetReceipt`

### 11.4 GetReceipt 接口

协议 SHOULD 支持：

```text
GetReceipt(addr, seq)
GetReceiptByRef(BundleRef)
```

响应：

```text
ReceiptResponse {
  status
  receipt
}
```

### 11.5 缓存与持久化策略

协议层建议：

- 共识节点 SHOULD 至少缓存最近 `R` 个区块的最小 Receipt
- 用户节点 MUST 对自己的 Receipt 长期持久化
- 用户节点 MUST 在对应 Value 仍可能被后续验证引用时，保留自己的 `BundleSidecar`
- 用户钱包 SHOULD 按 `bundle_hash` 去重存储 `BundleSidecar`

实现层建议：

- V2 用户侧的 Receipt / Bundle 持久化 SHOULD 继承 V1 的“共享对象池 + Value 映射 + 顺序字段”思路，而不是在每个 Value 记录里复制完整对象。
- V1 中 `AccountProofStorage` / `AccountProofManager` 的数据库组织方式值得复用，但 V2 的共享对象应从 `ProofUnit` 改为 `ConfirmedBundleUnit` 与 `BundleSidecar`。
- 原 V1 的 `unit_id` 生成方式和 `reference_count` 更新逻辑不得原样照搬；V2 必须使用确定性对象 ID，且只有在映射真正新增时才增加引用计数。

如果超出缓存期仍未取回 Receipt，则恢复责任回到用户自身或其历史交易对手。

---

## 12. 用户侧本地数据结构

### 12.1 Value

V2 继续沿用 EZchain 的 Value 区间表示。

### 12.2 Value 状态

用户钱包 SHOULD 维护至少以下状态：

- `SPENDABLE`
- `PENDING_BUNDLE`
- `RECEIPT_MISSING`
- `LOCKED_FOR_VERIFICATION`
- `ARCHIVED`

### 12.3 本地 WitnessV2

对每个 Value / ValueRange：

```text
LocalValueRecord {
  value
  witness_v2
  checkpoint_set
  local_status
}
```

说明：

- 若当前 owner 还没有自取得该 Value 后提交过任何已确认 Bundle，则本地保存的 `witness_v2.confirmed_bundle_chain` 可以为空。
- `confirmed_bundle_chain` 在协议语义上是 `ConfirmedBundleUnit` 的有序序列；具体实现时 SHOULD 通过 `bundle_hash -> BundleSidecar` 的本地缓存做去重，避免在多个 Value 记录中复制同一份 Bundle 内容。

工程上，用户侧本地数据库 SHOULD 至少拆成以下几层：

```text
LocalWalletDB {
  ValueStore
  ConfirmedUnitStore
  SidecarStore
  CheckpointStore
}
```

推荐迁移关系：

- `ValueStore` 可继承 V1 `AccountValueCollection` 的 SQLite 持久化、状态索引、顺序字段与热点缓存思路。
- `ConfirmedUnitStore` 可继承 V1 `AccountProofManager` 的“唯一对象表 + 映射表 + sequence”思路，但对象从 `ProofUnit` 改为 `ConfirmedBundleUnit`。
- `SidecarStore` 是 V2 新增的共享对象池，按 `bundle_hash` 去重保存本地 Bundle 内容。
- `CheckpointStore` 可继承 V1 `CheckPointStorage` 的 upsert + cache 模式，但记录字段必须扩展到 `block_hash` / `bundle_ref`。

### 12.4 为什么不能“漏领 Receipt 仍继续安全花费”

如果某个 Value 对应的最新 sender 证明段缺失 Receipt，则：

- 用户无法向下一跳 recipient 提供完整 Witness
- 因此该 Value 必须进入 `RECEIPT_MISSING` 或 `LOCKED_FOR_VERIFICATION`

但是这不应冻结整个账户。

正确语义是：

> 缺 Receipt 的是具体 Value，不是整个地址。

### 12.5 Sidecar GC 规则

Sidecar（`BundleSidecar`）按 `bundle_hash` 去重存储，是 Witness 重建的核心依赖。Sidecar GC MUST 遵守以下规则：

1. **被 active checkpoint 引用的 sidecar MUST NOT 被 GC。** "active checkpoint"定义为：存在一个本地 Value 记录（`local_status != ARCHIVED`），其对应的 Checkpoint 的 `checkpoint_bundle_hash == compute_bundle_hash(sidecar)`。
2. **被 pending bundle 引用的 sidecar MUST NOT 被 GC。** 即 `pending_bundles` 表中 `bundle_hash` 对应的 sidecar 不得删除。
3. **被 `WITNESS_INCOMPLETE` 状态 Value 引用的 sidecar（若仍存在）MUST NOT 被 GC。**
4. 当 Value 被花费/转出（`local_status -> ARCHIVED`）且不存在其他 Value 引用同一 sidecar 时，该 sidecar 成为 GC 候选。但其对应的 checkpoint 在所有引用该 sidecar 的 Value 都归档后才可标记为 "superseded"。
5. **GC MUST NOT 在 `_persist_records` 的 `replace_value_records` 与 `recompute_sidecar_ref_counts` 之间运行。** 工程实现应确保这两步在同一个原子事务或互斥锁内完成。

违反以上任一规则的 GC 行为都可能导致 Value 变成"死值"：owner 无法重建全量 Witness，后续无法转给不信任同一 Checkpoint 的第三方。

---

## 13. 用户提交流程

### 13.1 选值

sender 从本地 `SPENDABLE` 值集合中选择若干 Value。

选值策略 MAY 自定义，但必须满足：

1. 只选择本地可花费的值
2. 不选择 `RECEIPT_MISSING` 的值
3. 不选择已被挂入 `PENDING_BUNDLE` 的值

### 13.2 Value split

若支付额与某个 Value 不完全匹配，则允许分裂。

规则：

1. 分裂结果 MUST 是互不相交的子区间
2. 支付区间与找零区间并集必须等于原 Value
3. 两者的 Witness 初始继承自原 Value

### 13.3 Bundle 构造

sender 将当前时间窗内的若干 `OffChainTx` 打包进一个 `BundleSidecar`。

然后：

1. 计算 `bundle_hash`
2. 计算 `claim_set_hash`
3. 根据链上最新已确认 seq 生成 `BundleEnvelope`
4. 签名
5. 广播给共识节点

### 13.4 本地锁定

一旦 Bundle 提交：

- 被选中的 Value SHOULD 标记为 `PENDING_BUNDLE`

若 Bundle 到期未上链：

- 钱包可将其回滚为 `SPENDABLE`

---

## 14. Receipt 到账后的用户侧更新

### 14.1 sender 收到 Receipt 后

sender MUST：

1. 验证 Receipt 自身合法性
2. 使用本地提交时保存的 `BundleSidecar` 与 Receipt 组装出 `ConfirmedBundleUnit`
3. 将该 `ConfirmedBundleUnit` 追加到本地相关 Value 的 `confirmed_bundle_chain`
4. 把相关 Value 的本地状态从 `PENDING_BUNDLE` 更新为新的已确认状态

在轻量设备上，`BundleEnvelope` 在对应 Receipt 到账且不再需要重发后，MAY 被回收；但 `BundleSidecar` 在相关 Value 仍可能被后续验证引用前，不得提前删除。

### 14.2 当前 sender 证明段的更新

当 owner 自己提交一个新 Bundle 时，涉及的 Value 按如下规则更新 Witness：

1. 若某 Value 在该 Bundle 后仍归当前 owner 持有，则将新的 `ConfirmedBundleUnit` 追加到该 Value 的 `confirmed_bundle_chain`。
2. 若某 Value 在该 Bundle 中被转移给他人，则该 Value 对当前 owner 的这段 `confirmed_bundle_chain` 在此 `ConfirmedBundleUnit` 处封口，并作为发给 recipient 的 Witness 一部分输出。
3. 若某 Value 被拆分为多个子区间，则各子区间初始继承相同的 `anchor` 与当前已经形成的 `confirmed_bundle_chain`，之后再各自独立演化。

这里的关键点是：

- Witness 不是按账户全局保存一份，而是按 Value 或 ValueRange 保存。
- 同一 owner 未来若再次取得该 Value，则会从新的获得事件开始形成一段新的 `confirmed_bundle_chain`。

---

## 15. P2P 交易与验证规范

### 15.1 发送给 recipient 的数据

sender 在 P2P 阶段必须发送：

```text
TransferPackage {
  target_tx
  target_value
  witness_v2
}
```

### 15.2 recipient 必须完成的验证

recipient MUST 验证：

1. `witness_v2.confirmed_bundle_chain` 非空
2. `target_tx` 确实存在于 `witness_v2.confirmed_bundle_chain` 的最新 `ConfirmedBundleUnit.bundle_sidecar`
3. `target_tx.recipient == recipient`
4. `target_value` 与 `target_tx.value_list` 匹配
5. `witness_v2.current_owner_addr == target_tx.sender_addr`
6. `witness_v2.confirmed_bundle_chain` 从新到旧连续合法
7. 每个 `ConfirmedBundleUnit.receipt` 的 SMT 路径证明有效
8. `confirmed_bundle_chain` 内不存在对目标 Value 的非法提前花销
9. `witness_v2.anchor` 合法，且递归终止于 `GenesisAnchor` 或本地可信 `CheckpointAnchor`

### 15.3 当前 sender 证明段验证

设当前 sender 的已确认链为：

```text
U_k, U_(k-1), ..., U_1
```

其中每个 `U_i` 都是一个 `ConfirmedBundleUnit`，且 `U_k` 是最新单元，必须对应当前要支付给 recipient 的那个 Bundle。

recipient 必须验证：

1. `U_k.bundle_sidecar` 中存在且仅存在一次目标转移 `sender -> recipient`。
2. 用 `U_i.receipt + U_i.bundle_sidecar` 重建出的 `AccountLeaf` 必须能通过 `U_i.receipt.account_state_proof` 验证到 `U_i.receipt.header_lite.state_root`。
3. 对任意 `i > 1`，`U_i.receipt.prev_ref == confirmed_ref(U_(i-1))`。
4. 若 `confirmed_bundle_chain` 中任一处链断裂，则说明 sender 隐瞒了自己的某次 Bundle，验证失败。

这正是 V2 用来替代 V1 Bloom filter 的关键完整性机制。

### 15.4 递归锚点验证

recipient 在完成当前 sender 证明段验证后，必须继续验证 `anchor`：

1. 若 `anchor = GenesisAnchor`：
   - 检查该 Value 是否与创世分配记录一致。
   - 递归验证在此终止。
2. 若 `anchor = CheckpointAnchor`：
   - 检查本地是否存在匹配的可信 Checkpoint。
   - 若匹配，则递归验证在此终止。
3. 若 `anchor = PriorWitnessLink`：
   - 递归验证 `prior_witness`。
   - 在 `prior_witness` 的最新 `ConfirmedBundleUnit.bundle_sidecar` 中，检查 `acquire_tx` 是否真实存在。
   - 检查 `acquire_tx.recipient == witness_v2.current_owner_addr`。
   - 检查 `acquire_tx.value_list` 中确实包含 `target_value`。
   - 检查当前 sender 的最早 `ConfirmedBundleUnit` 若存在，则其区块高度必须严格晚于 `acquire_tx` 所在区块。

换言之，V2 的链下验证不是把所有 owner 平铺成一个数组，而是“验证当前 sender 一段，再递归进入前一 sender 的 Witness”。

### 15.5 当前 Bundle 内部冲突检查

由于 `claim_set_hash` 已被该 `ConfirmedBundleUnit` 对应的 `AccountLeaf` 承诺，recipient MAY 先用它做负向过滤；但只要目标 Value 可能命中，recipient 仍 MUST 扫描目标 `ConfirmedBundleUnit` 的整个 `bundle_sidecar`，检查：

1. 是否存在多个 tx 共同使用同一目标 Value
2. 是否存在与目标 Value 区间相交的其他 tx
3. 是否存在同一 Value 被发往多个 recipient 的情形

若存在，则直接拒绝。

### 15.6 历史 Bundle 冲突检查

recipient 对 `confirmed_bundle_chain` 中每个 `ConfirmedBundleUnit.bundle_sidecar` 也必须执行“目标 Value 交叉检查”：

- 若该单元不是当前这段 sender 历史的末端转移块，则其中任何与目标 Value 相交的 tx 都视为双花
- 若该单元是末端转移块，则仅允许唯一的合法转移 tx 与目标 Value 完全一致

### 15.7 接受条件

recipient 仅当全部验证通过时，才能接受该 Value，并将其写入本地 VWDB / WitnessV2 存储。

### 15.8 recipient 落账后的 Witness 重基

recipient 接受该 Value 后，MUST 将收到的转账证明重写为“以自己为当前 owner”的本地 Witness：

```text
accepted_witness = WitnessV2 {
  value = target_value
  current_owner_addr = recipient
  confirmed_bundle_chain = []
  anchor = PriorWitnessLink {
    acquire_tx = target_tx
    prior_witness = received_witness_v2
  }
}
```

这样做的目的，是把“上一跳 sender 的已确认历史”封装进 `prior_witness`，而把 recipient 自己未来的已确认 Bundle 历史单独积累在新的 `confirmed_bundle_chain` 中。

若 recipient 未来再次花费该 Value，则它提交的 TransferPackage 应基于这个 `accepted_witness` 演化后的最新版本。

### 15.9 Witness Completion 协议（旧 owner 重新接收场景）

#### 15.9.1 问题背景

当 Value 在不同 owner 之间流转时，可能出现如下场景：

1. Alice 将 Value V 转 Bob，附全量 Witness
2. Bob 验证接受 V，创建 Checkpoint C
3. Bob 将 V 转 Charlie，Witness 按 C 裁剪后发送
4. Bob 本地 pre-C 的 sidecar refcount 归零并被 GC
5. Charlie 将 V 转回 Bob，检测到 Bob 是旧 owner 且有 C，仅发送 C 之后的 witness 切片
6. Bob 接受 V 后欲转 Dave，但 Dave 不信任 C（C 是 Bob 自己创建的 checkpoint），需要全量 Witness 到 GenesisAnchor
7. Bob 本地 sidecar 已被删除，无法重建全量 Witness → V 变成死值

根本原因：checkpoint 是 owner 本地的优化对象，不是全局可信的。当 Value 离开再回来时，旧 owner 可能已经 GC 了重新构建全量 Witness 所需的 sidecar。

#### 15.9.2 协议规则

当 sender 检测到 recipient 是 Value 的旧 owner 且拥有匹配的 Checkpoint，并据此发送裁剪后的 TransferPackage 时，协议 MUST 遵守以下规则：

**规则 1：recipient 有权索取全量 Witness**

recipient 接收裁剪后的 TransferPackage 后，MUST 检查本地 sidecar 存储是否足以在将来重建全量 Witness（即追溯到 GenesisAnchor 或全局可信 Checkpoint 的完整 sidecar 集）。若不足，recipient MUST 向 sender 发起 Witness Completion Request。

```text
WitnessCompletionReq {
  target_value_begin
  target_value_end
  target_tx_hash          // 标识哪笔交易触发了此请求
  from_checkpoint_height  // 从哪个高度开始需要补充（recipient 本地已有的 checkpoint 高度，0 表示需要全量）
}
```

**规则 2：sender 有义务提供全量 Witness**

sender 收到 WitnessCompletionReq 后，MUST 回复从 `from_checkpoint_height` 对应位置到 GenesisAnchor（或 sender 自身的可信 Checkpoint）的完整 witness 切片，包含全部 sidecar。

```text
WitnessCompletionResp {
  target_value_begin
  target_value_end
  target_tx_hash
  completion_witness   // 从 from_checkpoint_height 位置开始的完整 prior witness（未裁剪）
  sidecar_batch         // completion_witness 中引用的所有 BundleSidecar
}
```

sender MUST 在相关 Value 仍在本钱包中（包括已归档但尚未 GC sidecar 的 Value）期间，保留响应此类请求的能力。

**规则 3：recipient MUST 恢复完整 sidecar 后才能花费**

recipient 收到 WitnessCompletionResp 后，MUST：

1. 将 `sidecar_batch` 中的所有 BundleSidecar 写入本地 sidecar 存储
2. 验证 `completion_witness` 的正确性（递归 SMT proof + prev_ref 连续性）
3. 将裁剪后的 accepted_witness 替换为包含完整 prior witness 的版本
4. 此后 Value 才可被标记为 `VERIFIED_SPENDABLE`

若 sender 不可达或拒绝提供，recipient MUST 将该 Value 标记为 `WITNESS_INCOMPLETE`（新增状态），该 Value 不可花费但保留在钱包中等待将来恢复。

**规则 4：Sidecar GC MUST NOT 删除被 active checkpoint 引用的 sidecar**

此规则防止 recipient 在获得全量 Witness 之前再次丢失 sidecar。详见 §12.3 中更新的 GC 约束。

#### 15.9.3 状态机扩展

Value 状态枚举新增：

- `WITNESS_INCOMPLETE`：Value 已接收但 sidecar 不完整，无法重建全量 Witness，不可花费

状态转换：

```text
VERIFIED_SPENDABLE → (转出) → ARCHIVED
VERIFIED_SPENDABLE → (sidecar GC 后被检测) → WITNESS_INCOMPLETE
WITNESS_INCOMPLETE → (Witness Completion 成功) → VERIFIED_SPENDABLE
```

#### 15.9.4 安全分析

- **sender 不能伪造 completion_witness**：recipient 会验证 SMT proof 和 prev_ref 链，伪造的证据无法通过
- **sender 拒绝提供不影响已接收 Value 的安全性**：recipient 的 accepted_witness 中 sender 的证明段仍然有效（SMT proof 正确、prev_ref 连续），只是 anchor 之前的 witness 不完整。recipient 只是无法再将此 Value 转给不信任同一 checkpoint 的第三方
- **DoS 防护**：WitnessCompletionReq/Resp 消息 SHOULD 设置大小上限和超时；sender 对同一 recipient 的同一 Value 仅需响应一次

---

## 16. Checkpoint 机制

### 16.1 目标

Checkpoint 的目标是裁剪已经被本地完整验证过的旧递归 Witness 尾部，避免无限向创世块回溯。

### 16.2 触发条件

当某 owner 对一个 ValueRange 完成完整递归验证并接受到账后，MAY 为其记录 Checkpoint。

### 16.3 记录时机

owner 在完成一次完整 P2P 验证后，MAY 生成：

```text
Checkpoint {
  value_begin
  value_end
  owner_addr
  checkpoint_height
  checkpoint_block_hash
  checkpoint_bundle_hash
}
```

### 16.4 使用规则

当 owner 未来再次验证该 ValueRange 时，若递归 Witness 在某一层到达与 Checkpoint 匹配的锚点，则：

- Checkpoint 之前的全部递归历史可视为已验证
- 验证可从 Checkpoint 之后开始

### 16.5 安全约束

Checkpoint MUST 绑定：

1. ValueRange
2. owner_addr
3. block_hash
4. bundle_hash

不得仅绑定高度。

---

## 17. Genesis 规范

### 17.1 统一创世锚点语义

V2 必须为递归 Witness 提供统一的起点语义。

推荐做法是：

- 创世块中维护一份确定性的初始分配记录
- 对初始分配的 Value，Witness 以 `GenesisAnchor` 作为递归终点

### 17.2 GenesisAnchor 的作用

初始分配给某首位 owner 的 Value，其 Witness 起点为：

- 与该 Value 匹配的 `GenesisAnchor`

### 17.3 实现建议

工程实现上，`GenesisAnchor` 可以有两种等价方案：

1. 显式创世分配表 + 分配证明
2. 把创世分配视作特殊 Bundle，并为其构造伪 Receipt

本草案不强制二者选型，但要求全网语义唯一、验证规则唯一。

---

## 18. 失败语义与恢复语义

### 18.1 缺 Receipt

若某 Value 缺少最新 Receipt：

- 该 Value 进入 `RECEIPT_MISSING`
- 不得继续安全花费

恢复方式：

1. 从本地备份恢复
2. 从共识节点最近缓存恢复
3. 从交易对手恢复

### 18.2 缺递归前序 Witness

若 sender 无法提供某前序递归 Witness：

- recipient MUST 拒绝或延迟接受该交易

### 18.3 receipt 链断裂

若某 owner 的 `prev_ref` 链不连续：

- 视为该 owner 隐瞒了历史 Bundle
- 验证失败

### 18.4 分叉切换

若某 Receipt 对应块未最终确认，而底层链发生分叉回滚：

- 该 Receipt 作废
- 基于该 Receipt 生成的待验证交易必须重新获取新链上的 Receipt

因此：

- 用户侧 `SHOULD` 仅在区块足够确认后进行正式 P2P 收款接受

---

## 19. 安全分析与潜在攻击面

### 19.1 分叉歧义攻击

风险：

- 若只用区块高度引用历史，则不同分叉同高度会混淆

解决：

- `BundleRef` 必须包含 `block_hash`

### 19.2 签名可塑性攻击

风险：

- 高 `s` 值可导致可塑性问题

解决：

- 强制 `low-s`

### 19.3 跨链重放攻击

风险：

- 不同链复用同一签名

解决：

- `chain_id`
- `domain_separator`

### 19.4 proposer 差分等价攻击

风险：

- proposer 给不同共识节点发送不同排序或不同内容的 diff

解决：

1. `diff_root` 入块头
2. `diff_entries` 严格排序
3. 使用 SMT 固定叶位

### 19.5 同块内同 sender 冲突攻击

风险：

- 同一 sender 在同一块出现两次，会破坏“最新状态头指针”的唯一性

解决：

- 每块每 sender 至多一个 Bundle

### 19.6 单 Bundle 内部双花攻击

风险：

- sender 在同一 Bundle 中把同一 Value 发给多个 recipient

解决：

- recipient 必须扫描整个 BundleSidecar 做区间交叉检查
- 协议设置 Bundle 大小上限

### 19.7 历史省略攻击

风险：

- sender 隐瞒 owner 的某次旧 Bundle

解决：

- 通过 `prev_ref` 链校验完整性

### 19.8 递归前序 Witness 省略攻击

风险：

- sender 只给出当前自己的 `confirmed_bundle_chain`，但故意省略更早的前序 Witness，导致 recipient 无法确认该 Value 的获得路径

解决：

1. WitnessV2 必须终止于 `GenesisAnchor` 或本地可信 `CheckpointAnchor`
2. 若 `anchor = PriorWitnessLink`，则 recipient 必须继续递归验证 `prior_witness`
3. 任一层递归缺失，交易都不得通过

### 19.9 Receipt 丢失 DoS

风险：

- 用户漏领 Receipt 后无法继续安全花费

解决：

1. 只锁定具体 Value，不锁定整个账户
2. 推送优先，拉取兜底
3. 共识节点缓存最近 `R` 个区块 Receipt

### 19.10 超大 Witness DoS

风险：

- 恶意 sender 提供超长历史链拖垮 recipient

解决：

1. 使用 Checkpoint
2. 钱包设置最大验证预算
3. 协议层对 Bundle 大小设上限

### 19.11 Value 区间歧义攻击

风险：

- sender 利用无序、重叠或非规范化的 `value_list` 制造不同实现之间的验证分歧

解决：

1. `value_list` 必须按区间起点严格排序
2. 同一 `value_list` 内禁止重叠区间
3. 相邻区间是否自动合并必须由协议统一规定，不能由实现自行决定

### 19.12 非安全序列化攻击

风险：

- 若工程层继续使用 `pickle` 等不安全反序列化方式处理网络输入，可能引入远程代码执行或状态污染风险

解决：

1. 协议层统一采用 `canonical_encode`
2. 网络消息、磁盘持久化、签名输入均不得直接使用 `pickle`
3. 旧代码中的 `pickle` 逻辑在 V2 落地时必须迁移或隔离

---

## 20. 本草案新增发现的问题与解决方案

本节专门列出在展开 V2 详细设计时暴露出来、但在初始概念文档中不够显式的问题。

### 问题 1：Witness 需要“递归 sender 证明段”，而不能只是最新 Receipt

如果 Bob 只看到 Alice 当前这次上链 Receipt，那么 Bob 只能确认：

- Alice 的最新 Bundle 确实上链

但仍然无法完成完整溯源。

解决：

- WitnessV2 必须由“当前 sender 的 `confirmed_bundle_chain` + 前序递归锚点”组成

### 问题 2：普通 Merkle 列表不适合部分更新

解决：

- 强制使用 SMT

### 问题 3：diff 若不被承诺，会导致不同节点恢复结果不一致

解决：

1. `diff_root` 必须入块头
2. `DiffEntry` 必须严格排序
3. 所有节点必须从同一旧 `state_root` 出发应用 diff

### 问题 3.1：Receipt 若设计过重，会浪费轻量设备的通信和存储预算

若 Receipt 直接携带完整 `BlockHeader`、`BundleEnvelope`、`BundleSidecar` 和完整叶子负载，就会把 sender 本地本就持有的数据再次从共识层回传一遍。

解决：

1. Receipt 缩减为 `HeaderLite + seq + prev_ref + account_state_proof`
2. P2P 验证单元改为 `ConfirmedBundleUnit = Receipt + BundleSidecar`
3. 用户侧对 `BundleSidecar` 按 `bundle_hash` 去重缓存

### 问题 4：引入 `claim_set_hash` 后的边界

引入 `claim_set_hash` 可以减少 recipient 对明显无关 Bundle 的完整扫描，但它只能做带链上锚点的负向过滤，不能替代正例验证：

- recipient 在 `claim_set_hash` 显示目标 Value 可能命中时，仍必须扫描整个 `BundleSidecar`

解决：

- 强制设置 Bundle 大小上限
- 将 `claim_set_hash` 明确纳入 `AccountLeaf` 承诺，并要求 leader / follower 从 `BundleSidecar` 重算校验

### 问题 5：Receipt 分发失败会影响 Value 活性

若 sender 丢失最新 Receipt，则相应 Value 暂时不可安全再花。

解决：

1. winner 出块后主动推送 Receipt
2. 共识节点维护最近 `R` 块的 Receipt 缓存
3. 钱包只锁定缺 Receipt 的具体 Value，不冻结整个账户

### 问题 6：同一 sender 多 Bundle 会破坏头指针唯一性

若同一 sender 在同一块中出现多个 Bundle，则 `head_ref` 的定义会失去唯一性。

解决：

1. 每块每 sender 至多一个执行中的 Bundle
2. 若实现替换机制，最多只允许同 `seq` 覆盖旧待处理项

### 问题 7：值分裂与找零后的 Witness 继承规则必须统一

解决：

1. 分裂产生的所有子区间初始继承父 Value 的 WitnessV2
2. 子区间在后续交易中再各自形成新的 sender 证明段
3. 协议必须禁止“只复制一半 Witness 给部分子区间”的实现

### 问题 8：值合并（merge）策略不清晰

若把两个相邻 Value 合并，但其 Witness 历史不同，可能破坏可验证性。

解决：

- 钱包仅可在两个 Value 的 Witness 从当前 Checkpoint 起完全一致时执行本地 merge
- 否则禁止 merge

### 问题 9：重组（reorg）下 Receipt 的确认深度需要统一

若用户在区块尚未充分确认时就接受 Value，则可能在链重组后拿到失效 Witness。

解决：

- 钱包侧必须设置最小确认深度
- 未达确认深度的 Receipt 只能标记为 `UNFINALIZED`

### 问题 10：当前代码中的序列化方式存在工程安全风险

现有仓库中多处对象使用 `pickle` 进行序列化，这对于 V2 的联网协议是高风险的。

解决：

- V2 必须统一迁移到规范二进制编码
- `pickle` 仅可用于完全离线、可信的开发调试场景，不能进入正式协议路径

### 问题 11：recipient 收款后，Witness 的 owner 语义需要重基

若 recipient 只是把 sender 发来的 Witness 原样存盘，则 `current_owner_addr` 仍然指向上一跳 sender，后续再花费时会发生语义混乱。

解决：

- recipient 接受交易后，必须执行一次 Witness 重基
- 重基后的本地 Witness 以 recipient 自己为 `current_owner_addr`
- 上一跳 sender 的完整证明作为 `PriorWitnessLink.prior_witness` 保留下来

### 问题 12：Sidecar GC 与 Witness 完整性冲突导致 re-received Value 变成死值

#### 问题描述

Witness 完整性依赖于本地 sidecar 存储。当 recipient 曾经持有某 Value 并为其创建了 Checkpoint，后续该 Value 经过多手转移后再次回到该 recipient 时，存在以下致命场景：

1. Alice 将 Value V 转 Bob，附带全量 Witness W
2. Bob 验证接受 V，创建 Checkpoint C（绑定 V 的精确区间、Bob 地址、当时的 block_hash 和 bundle_hash）
3. Bob 将 V 转 Charlie，发送时 Witness 按 C 裁剪（只发 C 之后的 witness 切片）
4. Bob 本地 pre-C 的 sidecar 因 ref_count 归零被 GC 删除
5. Charlie 将 V 转回 Bob，检测到 Bob 是 V 的旧 owner 且有 Checkpoint C，仅发送 C 之后的 witness 切片
6. Bob 接受 V，后续欲将 V 转 Dave
7. Dave 不信任 C（C 是 Bob 自己创建的 Checkpoint，Dave 的 `trusted_checkpoints` 中没有 C），要求 Witness 回溯到 `GenesisAnchor`
8. Bob 本地 pre-C 的 sidecar 已被删除，无法重建全量 Witness
9. **V 变成死值**：Bob 持有 V 但无法为其构造合法的 TransferPackage

这个问题的本质是：**Checkpoint 是本地优化对象，不是全局信任锚**。Checkpoint 的创建者信任它，但第三方不信任。当 Value 流转到第三方后再回来时，第三方裁剪所依据的 Checkpoint 对新的下一跳 recipient 无效。

#### 解决

本问题需要协议层和工程层双重修复：

**协议层（新增 §15.9 Witness 完整性恢复协议）**：

1. 当 recipient 收到被裁剪的 TransferPackage 时，若本地缺少重建全量 Witness 所需的 sidecar，recipient 有权向 sender 发起 `WitnessCompletionReq` 请求全量（未裁剪的）Witness
2. sender 收到 `WitnessCompletionReq` 后，MUST 返回该 Value 的完整 TransferPackage（anchor 回溯到 `GenesisAnchor` 或 sender 本地可信的最早 Checkpoint）
3. recipient 收到全量 Witness 后，MUST 将所有 sidecar 写入本地存储，确保后续再花费时能重建全量 Witness
4. sender MUST 在相关 Value 仍在自己钱包中（包括已归档但尚未 GC sidecar 的 Value）期间，保留提供全量 Witness 的能力

**工程层（Sidecar GC 规则强化，更新 §12.3）**：

1. 被 active checkpoint 引用的 sidecar MUST NOT 被 GC
2. "active checkpoint"定义为：对应的 Value 仍在本钱包中（`local_status != ARCHIVED`），且该 checkpoint 是此 Value 的最新 checkpoint
3. 当 Value 被花费/转出（`local_status -> ARCHIVED`），其 checkpoint 变为 "superseded"，引用的 sidecar 允许 GC
4. 但若该 Value 后来被 re-received（同一地址再次成为 owner），钱包 MUST 通过 Witness Completion 恢复完整 sidecar 存储后再标记为 `VERIFIED_SPENDABLE`

---

## 21. 工程落地建议

本节给出基于当前 `EZchain-V1` 代码库的模块级迁移清单。详细版见同目录下的：

- `EZchain-V2-module-migration-checklist.md`

### 21.1 迁移总原则

V2 不应该“从零推翻 V1 的本地数据库工程经验”，也不应该“把 V1 的 Bloom/VPB 语义硬搬过来”。

应遵守以下原则：

1. 继承 V1 的 SQLite、对象池、映射表、缓存、顺序字段这些工程方法。
2. 重写 V1 的协议对象本体，从 `ProofUnit / BlockIndex / SubmitTxInfo` 切换到 `Receipt / ConfirmedBundleUnit / BundleEnvelope`。
3. 任何网络消息、签名输入、跨节点对象传输，不得继续使用 `pickle`。
4. 任何历史合法性验证，不得继续依赖 Bloom。
5. 任何共享对象 ID，都必须由规范编码后的内容确定性生成。

### 21.2 模块级迁移清单

#### A. 可基本继承

1. `EZ_VPB/values/Value.py`
   - 保留区间表示、split、相交/包含判断。
   - 仅调整状态枚举以适配 V2。
2. `EZ_Tool_Box/SecureSignature.py`
   - 保留确定性 JSON 签名思路。
   - 新增 `BundleEnvelope` 签名与验签接口。
3. `modules/ez_p2p/security.py` 与 `modules/ez_p2p/codec/json_codec.py`
   - 可作为 V2 P2P 编码与消息签名的基础。
   - 需补 V2 消息类型与字段校验。

#### B. 保留架构模式，重写对象语义

1. `EZ_VPB/values/AccountValueCollection.py`
   - 保留 SQLite 持久化、状态索引、sequence、缓存。
   - 重写为 `ValueStore` / `LocalValueRecord`。
2. `EZ_VPB/values/AccountPickValues.py`
   - 保留本地值选择框架。
   - 重写选值策略，使其感知 `RECEIPT_MISSING`、checkpoint 距离和 witness 长度。
3. `EZ_CheckPoint/CheckPoint.py`
   - 保留 upsert、缓存、按 owner/高度查询的工程模式。
   - 扩展为绑定 `block_hash` 与 `bundle_ref` 的 `CheckpointRecordV2`。
4. `EZ_VPB/proofs/AccountProofManager.py`
   - 强烈建议保留“唯一对象表 + Value 映射表 + sequence”模式。
   - 共享对象从 `ProofUnit` 改为 `ConfirmedBundleUnit` / `BundleSidecar`。
   - 必须修正 V1 中非确定性 ID 与重复加引用问题。
5. `EZ_VPB/block_index/AccountBlockIndexManager.py`
   - 保留缓存、merge、按 value 定位历史索引的思路。
   - 语义重写为 `ReceiptRefIndex` / `PriorWitnessLinkStore`。
6. `EZ_Account/Account.py`
   - 保留统一编排入口。
   - 所有公开操作重写为围绕 `Receipt`、`WitnessV2`、`TransferPackage` 的新流程。

#### C. 必须重写

1. `EZ_Main_Chain/Block.py`、`EZ_Main_Chain/Blockchain.py`
   - 重写为 `state_root + diff_root + DiffPackage` 的 V2 主链结构。
2. `EZ_Transaction/MultiTransactions.py`、`EZ_Transaction/SubmitTxInfo.py`、`EZ_Tx_Pool/TXPool.py`
   - 重写为 `BundleEnvelope`、`BundleSidecar`、`BundlePool`。
3. `EZ_VPB/proofs/ProofUnit.py`、`EZ_VPB/proofs/Proofs.py`
   - 旧 proof 对象在 V2 中不再成立。
4. `EZ_VPB/block_index/BlockIndexList.py`
   - 旧验证逻辑依赖 Bloom，必须重写。
5. `EZ_VPB_Validator/`
   - V1 验证器应单独退役，V2 新建 `EZ_V2_Validator/`。
6. `EZ_Units/MerkleProof.py`
   - V2 需要适配 SMT 的 proof 结构，旧普通 Merkle proof 不宜直接复用。

### 21.3 存储表迁移建议

V2 建议延续 V1 的“轻量 SQLite + 对象表/映射表分离”方案，但表语义需更新：

1. `value_data` -> `value_records`
   - 存本地 Value/ValueRange、状态、最近 receipt 引用。
2. `proof_units` -> `confirmed_bundle_units` + `bundle_sidecars`
   - 前者存最小确认单元，后者按 `bundle_hash` 去重存 Bundle 内容。
3. `account_value_proofs` -> `value_confirmed_units`
   - 继续保留 `sequence`，表示某 Value 的本地有序确认链。
4. `block_indices` -> `value_receipt_refs`
   - 不再记 Bloom 命中高度，改记 `bundle_ref / prev_ref / HeaderLite` 等最小确认锚点。
5. `checkpoints` -> `checkpoints_v2`
   - 扩展为 exact-range checkpoint，并绑定 `block_hash` 与 `bundle_ref`。

### 21.4 当前仓库可直接借鉴的工程经验

1. 用 SQLite 做本地用户数据库是正确方向，适合消费级设备。
2. “共享对象池 + 映射表 + sequence”是 V2 Witness 存储最值得继承的模式。
3. `Account` 作为统一编排入口的分层方向是对的。
4. Checkpoint 的缓存与 upsert 设计值得保留。

### 21.5 当前仓库不得原样复用的实现

1. `ProofUnit.unit_id` 的旧生成逻辑。
2. `AccountProofManager` 里先增引用再判重的旧流程。
3. `BlockIndexList.verify_index_list()` 的 Bloom 依赖。
4. `MultiTransactions`、`SubmitTxInfo`、`Block`、`TXPool` 中的 `pickle` 编码路径。
5. V1/legacy 与新接口并存的双轨 proof 管理结构。

### 21.6 先实现什么

建议按以下顺序落地：

1. `BundleEnvelope / BundleSidecar` 编码与签名
2. SMT 与 `AccountLeaf`
3. `DiffEntry / DiffPackage / diff_root`
4. `BlockHeaderV2` 与出块/验块
5. `Receipt` 生成与拉取接口
6. `ConfirmedBundleUnit / BundleSidecar` 共享对象池
7. `ValueStore / ReceiptRefIndex / WitnessV2` 本地存储
8. V2 P2P 验证器
9. `CheckpointRecordV2`

### 21.7 不建议一开始就做的内容

1. Verkle tree
2. ZKP 压缩 Witness
3. 复杂数据可用性编码
4. 高级 mempool 排序与未来 seq 队列

---

## 22. 未来可选升级

以下内容不属于本草案强制要求，但未来可作为 V2.x 升级方向：

1. Verkle tree 替代 SMT，缩短 proof
2. Receipt 归档服务节点
3. Witness 压缩与批量证明
4. 更智能的 Checkpoint 策略

---

## 23. 结论

EZchain-V2 在不采用 Bloom filter 的前提下，仍然可以保持原系统的安全逻辑，但必须满足以下关键条件：

1. 主链采用固定叶位的 SMT
2. 区块头纳入 `diff_root`
3. sender 历史完整性通过 `prev_ref` 链保证
4. Witness 必须以递归 sender 证明段的形式终止于创世锚点或本地 Checkpoint
5. Receipt 必须最小化，只携带用户本地无法自行恢复的链上确认信息
6. 用户侧 Bundle 内容必须按需保存并按 `bundle_hash` 去重
7. Checkpoint 必须绑定 `block_hash + bundle_hash`

如果以上条件满足，则 V2 可以被视为：

> 使用 SMT + Receipt + prev_ref 链，对 V1 中 Bloom-based sender activity index 的一次精确化替换

而不是对 EZchain 原始安全模型的推翻。

---

## 24. 参考成熟方案

以下成熟方案对本文档中的若干设计点提供了启发：

- Jellyfish Merkle Tree（批量更新、固定键状态树、proof 返回）  
  https://diem.github.io/diem/diem_jellyfish_merkle/index.html

- Nervos Sparse Merkle Tree（稀疏默克尔树、存在性与不存在性证明）  
  https://github.com/nervosnetwork/sparse-merkle-tree

- Ethereum Research: proof-friendly state tree transitions（基于稀疏状态树的变更证明思路）  
  https://ethresear.ch/t/data-availability-proof-friendly-state-tree-transitions/1453

- EIP-155（chain_id 防跨链重放）  
  https://eips.ethereum.org/EIPS/eip-155

- EIP-2（low-s 防签名可塑性）  
  https://eips.ethereum.org/EIPS/eip-2

- Geth txpool 文档（同 nonce 交易池替换、pending/queued 分层思想）  
  https://geth.ethereum.org/docs/interacting-with-geth/rpc/ns-txpool
