# EZchain-V2 代码级优化清单

本文件基于对 `EZ_V2/` 全部核心实现代码的逐行审查，列出传输、存储、计算、数据格式四个维度的具体优化点。与 `CONSENSUS_OPTIMIZATION_LIST.md`（架构级优化）互补，本文件聚焦**已有代码中可直接修正的浪费和冗余**。

所有条目标注了具体的文件和行号，可立即定位和动手修改。

---

## 一、传输成本

### 1.1 网络传输用 JSON，而二进制编码器已写好却没用

**位置**：`serde.py`（全部），`encoding.py`（已有 `canonical_encode`）

**问题**：所有 bytes 字段序列化为 `{"__bytes__":"<hex>"}`。一个 32 字节哈希变成 74 字节。SMT proof 有 256 个兄弟节点哈希：

| 编码方式 | 单个 32B 哈希 | 256 个兄弟节点（SMT proof） |
|---------|-------------|--------------------------|
| 二进制 (canonical_encode) | 37 字节（1+4+32） | ~8 KB |
| JSON (serde) | 74 字节 | ~20 KB |

`encoding.py` 的 `canonical_encode()` 已实现完整的二进制编码（类型前缀 + 长度前缀 + 值），目前只用于签名哈希计算，未用于网络传输。

**预估收益**：单轮共识（4 节点、1 块）节省 35–60 KB。Receipt 交付每个省 ~12 KB。

**改法**：`NetworkEnvelope` 的 payload 序列化从 `dumps_json()` 切换为 `canonical_encode()`，或在传输层增加二进制模式开关。需同步修改接收端的反序列化路径。

---

### 1.2 完整区块在共识三个阶段各发一遍

**位置**：`network_host.py:1141-1153`

**问题**：`_drive_phase_over_network` 在 PREPARE、PRECOMMIT、COMMIT 每个阶段都把完整 `BlockV2`（含 DiffPackage、所有 Sidecar、签名、PEM 公钥）发给 N-1 个验证者。4 节点场景下：3 阶段 × 3 次 = **9 次全量传输**。

**改法**：PREPARE 阶段发送完整区块，PRECOMMIT 和 COMMIT 阶段只发 `Proposal + phase + justify_qc`，验证者通过 `proposal.block_hash` 从本地缓存取区块。

**预估收益**：每轮省 ~6 × 区块体积（约 60 KB）。

---

### 1.3 block_announce 把完整区块推给所有 Account 节点

**位置**：`network_host.py:1327-1348`，`_encode_block()` at L1386

**问题**：Account 节点收到完整 `BlockV2`，但它只需要 `height + block_hash + state_root`（约 130 字节）来判断自己是否在该块的 diff 中。完整区块可以按需 `block_fetch_req` 拉取。

**改法**：`_broadcast_block_announce` 只发 header 元数据，不发 `"block": block`。Account 节点在收到 `receipt_index_broadcast`（优化 1 的索引广播）或本地判断需要完整区块时，再主动拉取。

**预估收益**：M 个 Account 节点 × (区块体积 - 130 字节) / 块。以 10 个 Account 节点、10 KB/块计，每块省 ~100 KB 带宽。

---

### 1.4 consensus_finalize 再次重发完整区块

**位置**：`network_host.py:1371-1378`

**问题**：`consensus_finalize` 消息携带完整 `BlockV2 + commit_qc`。验证者在 proposal 阶段已经收到过区块，finalize 只需发 `commit_qc`，区块通过 hash 引用。

**改法**：`MSG_CONSENSUS_FINALIZE` 的 payload 改为 `{"block_hash": ..., "commit_qc": ...}`。

**预估收益**：每轮省 (N-1) × 区块体积。

---

### 1.5 SMT Proof 不压缩——256 个兄弟节点含大量默认值

**位置**：`smt.py` 的 `prove()` 方法

**问题**：`prove()` 始终返回 256 个兄弟节点哈希（`SparseMerkleProof.siblings` 固定长度 tuple）。但在稀疏树中，绝大多数兄弟节点是预设的 `_default_hashes`，只有少数是实际值。

100 个账户的树，每层约 log₂(100) ≈ 7 个非默认兄弟节点。压缩方式：只传 **(层级索引, 非默认哈希值)** 对。

| 编码 | 大小 |
|------|------|
| 当前（256 个哈希） | 8 KB binary / ~20 KB JSON |
| 压缩后（7–20 个非默认值 + 索引） | ~0.3–0.8 KB binary / ~0.5–1.5 KB JSON |
| **缩减** | **~95%** |

**改法**：`SparseMerkleProof` 增加压缩序列化方法 `to_compressed()` / `from_compressed()`。Receipt 和 Witness 中存储/传输压缩格式，验证时展开。

**预估收益**：每个 Receipt 省 ~7.5 KB，每个 ConfirmedBundleUnit 省 ~7.5 KB。这是传输和存储同时受益的改动。

---

## 二、存储成本

### 2.1 Sidecar 在数据库中存了多份

**位置**：`storage.py`（`confirmed_units` 表 L71-77，`bundle_sidecars` 表 L57-61）

**问题**：`confirmed_units` 表的 `unit_json` 包含完整 `ConfirmedBundleUnit`，其中包含完整 `BundleSidecar`。同一个 `BundleSidecar` 同时存在于 `bundle_sidecars` 表（以 `bundle_hash` 为主键）。

`confirmed_units.unit_json` 中的 sidecar 数据是纯粹冗余。

**改法**：`confirmed_units` 中只存 `bundle_hash` 引用，需要 sidecar 时从 `bundle_sidecars` 表按 hash 查询。

**预估收益**：每个 confirmed unit 省一个完整 sidecar 的 JSON 体积（数百字节至数 KB）。

---

### 2.2 ChainStateV2.blocks 列表无上限增长

**位置**：`chain.py:286`（初始化），`chain.py:460, 556`（追加）

**问题**：每个已确认或已应用的 `BlockV2`（含完整 DiffPackage、Sidecar、签名）永远追加到内存 `self.blocks: list[BlockV2]`。长时间运行后是内存泄漏。

**改法**：保留最近 N 个块（如 N=128）用于 Receipt 生成和回溯验证，更早的块持久化到磁盘或裁剪。添加 `max_blocks_in_memory` 参数和对应的淘汰逻辑。

---

### 2.3 value_records 表字段双重存储

**位置**：`storage.py:45-55`

**问题**：`value_records` 表同时存有独立列（`value_begin`、`value_end`、`local_status`、`acquisition_height` 等）和 `record_json TEXT` 字段。`record_json` 包含完整的 `LocalValueRecord` 序列化，其中重复了所有独立列的值。

**改法**：两种策略二选一：
- (a) 只保留 `record_json`，删除冗余列，需要查询的字段通过 SQLite JSON 函数（`json_extract`）索引
- (b) 只保留独立列 + `witness_json`（仅存 witness 部分），去掉 `record_json`

**预估收益**：每条记录省去标量字段的重复序列化。

---

### 2.4 accepted_transfer_packages 表只增不减

**位置**：`storage.py:96-101`，`storage.py:318-338`

**问题**：每笔收到的转账永久记录在 `accepted_transfer_packages` 表中，无清理机制。钱包生命周期内该表单调增长。

**改法**：添加基于时间的淘汰（如只保留最近 90 天）或基于数量的淘汰（如只保留最近 10000 条）。在 `_recompute_sidecar_ref_counts_locked` 中只扫描未过期的记录。

---

### 2.5 Receipt 在 ReceiptCache 中存了三份引用

**位置**：`chain.py:143-181`

**问题**：`ReceiptCache` 维护三个字典：`_by_height`、`_by_addr_seq`、`_by_ref`，每个 Receipt 对象在三个字典中各有一份引用。`_by_height` 中还额外存了一个 `BundleRef`（已包含在 Receipt 数据中）。`_by_ref` 的 key `(height, block_hash, bundle_hash, seq)` 中 `height` 是冗余的。

**改法**：合并为两个索引（`_by_height` 用于批量淘汰，`_by_addr_seq` 用于查询），`_by_ref` 的 key 简化为 `(block_hash, bundle_hash, seq)`。

---

## 三、计算成本

### 3.1 _prepare_entries() 在出块时被调用两次

**位置**：`chain.py:396-417`

**问题**：`_execute_submissions()` 中，`_prepare_entries()` 被调用两次——第一次用零 `block_hash` 算出真 hash 后丢弃结果，第二次用真 hash 重做全部工作（遍历 submissions、查找旧叶子、创建 DiffEntry/AccountLeaf/BundleRef）。

**改法**：两种方案：
- (a) 将 `BundleRef` 和 `DiffEntry` 中的 `block_hash` 延迟到真实 hash 计算后回填（需将相关 dataclass 改为可变或使用 builder 模式）
- (b) 在 `_prepare_entries` 中接受 `block_hash=None`，返回不含 block_hash 的中间结构，在 `derive_block_hash` 后一次性构造最终对象

**预估收益**：出块时的准备阶段耗时减半。

---

### 3.2 同一个列表在出块过程中被排序 5 次

**位置**：`chain.py:395-444`

**问题**：`_execute_submissions()` 中对 submissions 按 `compute_addr_key()` 排序 5 次（ provisional entries 排序、第二次 _prepare_entries 排序、entries 排序、sidecars 排序、sender_public_keys 排序），每次重新计算 `compute_addr_key()` = Keccak-256。

**改法**：在 `_execute_submissions` 入口处一次性排序并缓存 `addr_key`，后续直接复用排序结果。

**预估收益**：每次出块省 4k 次 Keccak-256 计算（k = sender 数量）。

---

### 3.3 SMT prove() 无缓存，批量生成 Receipt 时 O(k × N × 256)

**位置**：`smt.py:49-96`

**问题**：`prove()` 每次从零开始遍历整棵 `_values` 字典（每层递归分裂），不缓存任何子树哈希。生成 k 个 Receipt 时总复杂度 O(k × N × 256)，N 为树中总条目数。

**改法**：添加子树哈希缓存层。`root()` 和 `prove()` 共享缓存，`set()` 时使缓存失效。批量 prove 接口 `prove_batch(keys)` 一次遍历树收集所有需要的兄弟节点。

**预估收益**：批量 proof 生成从 O(k × N × 256) 降至 O(N × 256 + k × 256)。

---

### 3.4 ReceiptCache._prune() 每次 add 都排序

**位置**：`chain.py:157-165`

**问题**：`_prune()` 在每次 `add()` 时调用，内部执行 `sorted(self._by_height.keys())`。高度是单调递增的，排序完全多余。且 `_prune()` 即使在缓存远未满时也会执行。

**改法**：
- 用 `min_height` 变量跟踪最小高度，淘汰时直接 `pop(min_height)`
- 在 `add()` 中先判断 `len(_by_height) < max_blocks` 再调用 `_prune()`

**预估收益**：每次 Receipt 添加从 O(m log m) 降至 O(1)（m = 已缓存高度数）。

---

### 3.5 apply_block() 中同一 key 调用两次 dict.get()

**位置**：`chain.py:547`

**问题**：
```python
self.account_leaves.get(entry.new_leaf.addr).head_ref
    if self.account_leaves.get(entry.new_leaf.addr) else None
```
对同一个 key 连续调用两次 `.get()`。

**改法**：提取为局部变量 `old_leaf = self.account_leaves.get(entry.new_leaf.addr)`。

---

## 四、数据格式冗余

### 4.1 OffChainTx.sender_addr 在一个 Bundle 内重复 N 次

**位置**：`types.py:96-109`

**问题**：`BundleSidecar` 校验所有 `tx.sender_addr == self.sender_addr`（L107-109），但每个 `OffChainTx` 仍然独立存储 `sender_addr`。10 笔交易 = 10 份相同地址字符串。

**改法**：`OffChainTx` 中移除 `sender_addr` 字段，验证/序列化时从外层 `BundleSidecar.sender_addr` 获取。需调整 `validator.py` 和 `encoding.py` 中的引用。

**预估收益**：每个 bundle 省约 43 × tx_count 字节。10 笔交易省 ~430 字节。

---

### 4.2 DiffEntry.bundle_hash 与 bundle_envelope.bundle_hash 重复

**位置**：`types.py:156`

**问题**：`DiffEntry.bundle_hash` 与 `DiffEntry.bundle_envelope.bundle_hash` 存的是同一个 32 字节哈希。`apply_block()` 还专门校验两者一致（L509）。

**改法**：移除 `DiffEntry.bundle_hash` 字段，需要时从 `bundle_envelope.bundle_hash` 获取。

**预估收益**：每个 diff entry 省 37 字节（编码开销）。

---

### 4.3 PEM 公钥（~300 字节）全量传输存储

**位置**：`types.py:116`（BundleSubmission），`network_host.py:853`（bundle forward）

**问题**：`sender_public_key_pem` 是 PEM 格式公钥（含 `-----BEGIN PUBLIC KEY-----` 头部、base64 编码），约 200-400 字节。压缩公钥只需 33 字节。

**改法**：传输和存储时使用 33 字节压缩公钥（secp256k1 的 compressed point）。仅在签名验证时展开为完整公钥。PEM 格式只在本地 keystore 中保留。

**预估收益**：每次 bundle 提交/转发/存储省 ~250-370 字节。

---

### 4.4 PendingBundleContext 与 BundleSubmission 互相冗余

**位置**：`wallet.py:621-632`

**问题**：`PendingBundleContext` 存储了 `envelope`、`sidecar`、`sender_public_key_pem`——与 `BundleSubmission` 完全重复。另有 `sender_addr`、`bundle_hash`、`seq` 三个字段可从 envelope/sidecar 中派生。持久化时 `save_pending_bundle` 将整个 context 序列化为 JSON，sidecar 部分在 `save_sidecar` 中又存了一遍。

**改法**：`PendingBundleContext` 只存 `BundleSubmission` 的引用（或 bundle_hash + seq），需要完整数据时从 pool 或 sidecar 表查询。

---

### 4.5 编码器固定 4 字节长度前缀

**位置**：`encoding.py:8-11`

**问题**：所有字符串、字节、列表的长度字段固定 4 字节（`to_bytes(4, ...)`）。大部分协议字段很短（地址 ~42 字节、hash 32 字节、消息类型 ~25 字节），1-2 字节长度前缀就够。

**改法**：使用可变长度编码（类似 protobuf varint）：长度 < 128 用 1 字节，< 16384 用 2 字节，否则用 4 字节。编码/解码各增加一个分支判断。

**预估收益**：每个编码字段省 2-3 字节。一个 `BundleEnvelope` 约 15 个编码元素，省 ~30 字节。

---

### 4.6 dataclass 用字典键编码字段名

**位置**：`encoding.py:68-73`

**问题**：每个 dataclass 编码为字典，字段名作为字符串 key 编码。`BundleRef` 有 4 个字段（`height`、`block_hash`、`bundle_hash`、`seq`），字段名编码开销：

| 字段名 | 编码大小 |
|--------|---------|
| `"height"` (6 chars) | 11 字节 |
| `"block_hash"` (10 chars) | 15 字节 |
| `"bundle_hash"` (11 chars) | 16 字节 |
| `"seq"` (3 chars) | 8 字节 |
| **合计** | **50 字节** |

加上 dict 前缀 5 字节，一个 `BundleRef` 的结构开销 = 55 字节，而实际数据只有 ~90 字节。**开销占比 61%。**

**改法**：为每个 dataclass 分配字段序号映射表（如 `{"height": 0, "block_hash": 1, ...}`），编码时用 1 字节序号替代字段名字符串。需在协议层面约定映射表。

**预估收益**：每个 dataclass 省 40-80 字节。块中有多个 DiffEntry 各含多个嵌套 dataclass，累积节省可观。

---

## 五、网络层

### 5.1 每次 send 新建 TCP 连接，无连接池

**位置**：`network_transport.py:94-102`

**问题**：`send()` 每次新建 TCP 连接 → 请求 → 关闭。一轮共识约 15-20 次握手。WAN 环境下（50ms RTT）仅连接建立就消耗 ~1 秒。

**改法**：实现连接池，按 `host:port` 维护持久连接。服务端 `_handle_conn` 已支持持久循环（L132 的 `while True`），只需改客户端侧。

**预估收益**：消除 ~15-20 次 TCP 握手/轮。WAN 下每轮省 ~1 秒延迟。

---

### 5.2 NetworkEnvelope 每条消息都带 UUID + 时间戳

**位置**：`networking.py:48-53`

**问题**：每条消息的 envelope 包含：
- `request_id`：32 字符 hex UUID（37 字节编码）
- `created_at`：Unix 时间戳（7-10 字节编码）
- `msg_type`：完整字符串如 `"consensus_timeout_cert"`（25+ 字节编码）

对于广播类消息（`block_announce`、`peer_health`），`request_id` 无用。时间戳可由接收方自行记录。`msg_type` 可用 1 字节类型码替代。

**改法**：
- 广播消息不填 `request_id`
- `msg_type` 改为 uint8 类型码（当前约 18 种消息类型，一个字节够用）
- `created_at` 改为可选字段，仅超时敏感消息携带

**预估收益**：每条消息省 ~50-60 字节。

---

## 总览：按收益排序

| 排名 | 编号 | 优化点 | 类型 | 预估收益 |
|------|------|--------|------|---------|
| 1 | 1.1 | JSON→二进制传输 | 传输 | 所有消息体积减半 |
| 2 | 1.5 | SMT Proof 压缩 | 传输+存储 | 单 proof 20KB→0.5KB（95%） |
| 3 | 1.2 | 共识阶段不重发完整区块 | 传输 | 每轮省 6×区块体积 |
| 4 | 1.3 | block_announce 只发头 | 传输 | Account 节点带宽降 ~98% |
| 5 | 2.1 | Sidecar/Receipt 存储去重 | 存储 | 数据库体积减半+ |
| 6 | 3.3 | SMT prove() 加缓存 | 计算 | 批量 proof 从 O(kN×256)→O(N×256+k×256) |
| 7 | 3.1 | _prepare_entries 只调一次 | 计算 | 出块准备阶段减半 |
| 8 | 3.2 | 排序只做一次 | 计算 | 每次出块省 4k 次 Keccak |
| 9 | 4.1 | OffChainTx 去重 sender_addr | 格式 | 每个 bundle 省数百字节 |
| 10 | 5.1 | TCP 连接池 | 网络 | 消除 ~15-20 次握手/轮 |
| 11 | 4.3 | PEM→压缩公钥 | 格式+传输 | 每次 bundle 省 ~300 字节 |
| 12 | 1.4 | finalize 不重发区块 | 传输 | 每轮省 (N-1)×区块体积 |
| 13 | 2.2 | blocks 列表限长 | 存储 | 防止内存泄漏 |
| 14 | 4.5 | 可变长度前缀 | 格式 | 每个编码字段省 2-3 字节 |
| 15 | 4.6 | 字段序号编码替代字段名 | 格式 | 每个 dataclass 省 40-80 字节 |
