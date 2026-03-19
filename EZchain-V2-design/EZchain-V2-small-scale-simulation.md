# EZchain-V2 小规模真实案例推演与协议复核

## 0. 文档目的

本文档不是新的协议草案，而是对 [EZchain-V2-protocol-draft.md](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZchain-V2-design/EZchain-V2-protocol-draft.md) 的一次“带场景的压力测试”。

目标有两个：

1. 用一个足够具体的小规模网络，把 EZchain-V2 从创世块开始连续运行 4 个区块高度，尽量完整覆盖：
   - 用户选值与交易生成
   - Bundle 提交到 mempool
   - 共识节点并行打包与 leader 竞争
   - leader 出块、区块确认、Receipt 下发
   - sender 更新本地 VWDB / Witness 数据
   - sender 向 recipient 发送 `tx + witness`
   - recipient 验证与接受交易
   - Checkpoint 触发与后续使用
2. 在推演过程中主动寻找当前 V2 草案中还不够严密的地方，并给出修改建议。

本文档不计算具体哈希值、Merkle 路径和签名值，但会给出所有关键对象的“符号级”表示。

---

## 1. 场景设定

### 1.1 节点

共识节点共 4 个：

- `CN1`
- `CN2`
- `CN3`
- `CN4`

用户节点共 8 个：

- `Alice`
- `Bob`
- `Carol`
- `Dave`
- `Emma`
- `Frank`
- `Grace`
- `Helen`

### 1.2 共识假设

为便于推演，假设底层共识是一个轮次化的 BFT/PoS 混合过程：

1. 每个区块高度 `h` 开始时，所有共识节点对本地 mempool 做一次快照。
2. 每个共识节点都可以基于该快照构造候选块。
3. 每轮通过一个 VRF/优先级机制选出单个 leader。
4. 其余共识节点验证 `DiffPackage + state_root + diff_root` 后投票。
5. 当某候选块收集到 `3/4` 投票后，视为该高度最终确认。

为了简化叙述，本文设定：

- `height=1` 的 leader 是 `CN3`
- `height=2` 的 leader 是 `CN1`
- `height=3` 的 leader 是 `CN4`
- `height=4` 的 leader 是 `CN2`

### 1.3 记号

本文使用如下记号：

- `H0, H1, H2, H3, H4`：高度 `0..4` 的区块哈希
- `S0, S1, S2, S3, S4`：高度 `0..4` 的 `state_root`
- `D1, D2, D3, D4`：高度 `1..4` 的 `diff_root`
- `B_A1`：Alice 第 1 个 `BundleSidecar`
- `E_A1`：Alice 第 1 个 `BundleEnvelope`
- `R_A1`：Alice 第 1 个 Receipt
- `U_A1 = (R_A1, B_A1)`：Alice 第 1 个 `ConfirmedBundleUnit`
- `ref(A1)`：`B_A1` 被确认后形成的 `BundleRef`

### 1.4 创世块设定

参考 VWchain-V1 的 value 设计，创世块 `height=0` 采用“Value 是不相交整数区间”的设定。这里用一个缩小版的数轴：

| 用户 | 创世分配 Value |
| --- | --- |
| Alice | `[0,299]`, `[300,599]` |
| Bob | `[600,899]`, `[900,1199]` |
| Carol | `[1200,1499]` |
| Dave | `[1500,1799]`, `[1800,2099]` |
| Emma | `[2100,2399]` |
| Frank | `[2400,2699]` |
| Grace | `[2700,2999]` |
| Helen | `[3000,3299]` |

其余未分配区间：

- `[3300, 2^64 - 1]`

保留为未来区块激励与系统保留空间。

### 1.5 创世 Witness 初始状态

对于创世分配得到的每个 Value，用户本地初始 Witness 可视为：

```text
WitnessV2 {
  value = genesis_allocated_range
  current_owner_addr = owner
  confirmed_bundle_chain = []
  anchor = GenesisAnchor {
    genesis_block_hash = H0
    first_owner_addr = owner
    value_begin = ...
    value_end = ...
  }
}
```

也就是说，创世值在本地一开始：

- 没有自己的已确认 Bundle 历史
- 但有一个明确的创世锚点

---

## 2. 高度 1：首轮并行交易、打包、出块、P2P 验证

### 2.1 用户并行生成交易

在高度 1 开始前，三个用户几乎同时生成交易：

1. `Alice -> Bob : [0,99]`
2. `Dave -> Emma : [1500,1599]`
3. `Grace -> Alice : [2700,2749]`

对应地，三人本地都发生了 Value 切分：

- Alice 把 `[0,299]` 切成：
  - 支付值 `[0,99]`
  - 剩余值 `[100,299]`
- Dave 把 `[1500,1799]` 切成：
  - 支付值 `[1500,1599]`
  - 剩余值 `[1600,1799]`
- Grace 把 `[2700,2999]` 切成：
  - 支付值 `[2700,2749]`
  - 剩余值 `[2750,2999]`

### 2.2 用户提交 Bundle 到 mempool

三人构造 sidecar 和 envelope：

```text
B_A1 = {
  sender_addr = Alice,
  tx_list = [
    tx_A1_0: Alice -> Bob, value=[0,99]
  ]
}

B_D1 = {
  sender_addr = Dave,
  tx_list = [
    tx_D1_0: Dave -> Emma, value=[1500,1599]
  ]
}

B_G1 = {
  sender_addr = Grace,
  tx_list = [
    tx_G1_0: Grace -> Alice, value=[2700,2749]
  ]
}
```

然后分别签名生成：

- `E_A1`
- `E_D1`
- `E_G1`

三组 `Envelope + Sidecar` 被广播到共识网络。

### 2.3 共识节点并行处理 mempool

四个共识节点并行做以下事情：

1. 接收并校验三组 `Envelope + Sidecar`
2. 按 sender 建立索引
3. 检查：
   - `hash(sidecar) == bundle_hash`
   - 签名合法
   - `seq` 合法
   - `sender_addr` 一致
   - 大小限制合法
4. 将三组 Bundle 放入本地 mempool

由于当前还没有任何人提交过 post-genesis bundle，所以：

- `Alice.seq = 1`
- `Dave.seq = 1`
- `Grace.seq = 1`

### 2.4 leader 竞争与候选块生成

四个共识节点都基于相同 mempool 快照生成候选块，但本轮 leader 竞争中 `CN3` 获胜。

`CN3` 在高度 1 生成：

```text
Block_1 = {
  header = {
    height = 1
    prev_block_hash = H0
    state_root = S1
    diff_root = D1
    proposer = CN3
  }
  diff_entries = [
    Alice_update,
    Dave_update,
    Grace_update
  ]
}
```

对应账户状态叶更新为：

- Alice: `head_ref = ref(A1)`, `prev_ref = NULL`
- Dave: `head_ref = ref(D1)`, `prev_ref = NULL`
- Grace: `head_ref = ref(G1)`, `prev_ref = NULL`

其余账户叶保持不变。

### 2.5 高度 1 Receipt

区块确认后，`CN3` 为 3 个 sender 生成最小 Receipt：

```text
R_A1 = {
  header_lite = (height=1, block_hash=H1, state_root=S1)
  seq = 1
  prev_ref = NULL
  account_state_proof = pi_A1
}

R_D1 = {
  header_lite = (height=1, block_hash=H1, state_root=S1)
  seq = 1
  prev_ref = NULL
  account_state_proof = pi_D1
}

R_G1 = {
  header_lite = (height=1, block_hash=H1, state_root=S1)
  seq = 1
  prev_ref = NULL
  account_state_proof = pi_G1
}
```

然后：

- Alice 本地组装 `U_A1 = (R_A1, B_A1)`
- Dave 本地组装 `U_D1 = (R_D1, B_D1)`
- Grace 本地组装 `U_G1 = (R_G1, B_G1)`

### 2.6 sender 更新本地 VWDB / Witness

这一轮最关键。

#### Alice 更新后

Alice 当前仍持有：

- `[100,299]`，这是从 `[0,299]` 分裂出的剩余值
- `[300,599]`，这是她另一段创世值

二者都必须把 `U_A1` 追加到自己的 `confirmed_bundle_chain`，因为：

- 对未来 recipient 来说，Alice 在高度 1 确实提交过一个 Bundle
- 未来任何 recipient 都必须检查 `B_A1` 里是否偷偷花掉了目标值

所以，Alice 本地应更新为：

```text
W_A_[100,299] = {
  current_owner = Alice
  confirmed_bundle_chain = [U_A1]
  anchor = GenesisAnchor(H0, Alice, [0,299])
}

W_A_[300,599] = {
  current_owner = Alice
  confirmed_bundle_chain = [U_A1]
  anchor = GenesisAnchor(H0, Alice, [300,599])
}
```

#### Dave 更新后

Dave 当前仍持有：

- `[1600,1799]`
- `[1800,2099]`

这两个值也都必须追加 `U_D1`。

#### Grace 更新后

Grace 当前仍持有：

- `[2750,2999]`

该值追加 `U_G1`。

### 2.7 sender 向 recipient 发送 `tx + witness`

区块 1 确认后，三组 P2P 交付并行发生：

1. Alice 向 Bob 发送 `[0,99]`
2. Dave 向 Emma 发送 `[1500,1599]`
3. Grace 向 Alice 发送 `[2700,2749]`

以 Alice -> Bob 为例：

```text
TransferPackage_A_to_B = {
  target_tx = tx_A1_0
  target_value = [0,99]
  witness_v2 = {
    value = [0,99]
    current_owner_addr = Alice
    confirmed_bundle_chain = [U_A1]
    anchor = GenesisAnchor(H0, Alice, [0,299])
  }
}
```

Bob 的验证流程：

1. 检查 `tx_A1_0` 在 `B_A1` 中确实存在
2. 检查 `tx_A1_0.recipient == Bob`
3. 用 `R_A1 + B_A1` 重建 Alice 的 `AccountLeaf`
4. 用 `pi_A1` 验证该叶子在 `S1` 下存在
5. 扫描 `B_A1` 全部 tx，确认 `[0,99]` 没有冲突花销
6. 检查创世锚点确实把 `[0,299]` 分给了 Alice

通过后，Bob 本地生成：

```text
W_B_[0,99] = {
  value = [0,99]
  current_owner_addr = Bob
  confirmed_bundle_chain = []
  anchor = PriorWitnessLink {
    acquire_tx = tx_A1_0
    prior_witness = witness_v2_from_Alice
  }
}
```

注意：

- Bob 新持有 `[0,99]`
- 但 Bob 自己还没有任何已确认 Bundle
- 所以 `confirmed_bundle_chain = []`

Grace -> Alice 的 `[2700,2749]` 也会以同样方式进入 Alice 本地数据库。

---

## 3. 高度 2：递归 Witness、同一 sender 多 tx、回流值验证

### 3.1 高度 2 前的并行用户行为

区块 1 确认后，至少有三件事并行发生：

1. Alice 收到 Grace 转来的 `[2700,2749]`
2. Bob 收到 Alice 转来的 `[0,99]`
3. Emma 收到 Dave 转来的 `[1500,1599]`

随后，三人又继续并行生成新交易：

1. `Alice -> Carol : [2700,2749]`
2. `Alice -> Helen : [300,349]`
3. `Bob -> Frank : [0,99]`
4. `Emma -> Dave : [1500,1599]`

这四笔交易被打成 3 个 Bundle：

```text
B_A2 = {
  sender_addr = Alice
  tx_list = [
    tx_A2_0: Alice -> Carol, value=[2700,2749]
    tx_A2_1: Alice -> Helen, value=[300,349]
  ]
}

B_B1 = {
  sender_addr = Bob
  tx_list = [
    tx_B1_0: Bob -> Frank, value=[0,99]
  ]
}

B_E1 = {
  sender_addr = Emma
  tx_list = [
    tx_E1_0: Emma -> Dave, value=[1500,1599]
  ]
}
```

### 3.2 一个重要观察：两个值的历史长度不同

在 Alice 的 `B_A2` 里，有两个被花费的值：

1. `[2700,2749]`
2. `[300,349]`

这两个值的 current witness 长度不一样：

- `[2700,2749]` 是 Alice 在区块 1 之后才从 Grace 收到的
- 因此它不需要回溯 Alice 在区块 1 的历史
- 它在 Alice 本地的当前段是空链，锚点指向 Grace 的 prior witness

而 `[300,349]` 是 Alice 从创世块起一直持有的旧值的一部分：

- 因此它必须包含 `U_A1`
- 否则 Helen 无法检查 Alice 在 `B_A1` 中有没有提前花掉 `[300,349]`

这会在高度 2 的验证里直接暴露出一个非常重要的协议边界，后文会专门总结。

### 3.3 高度 2 leader 竞争与出块

本轮 `CN1` 胜出，出块：

```text
Block_2 = {
  header = {
    height = 2
    prev_block_hash = H1
    state_root = S2
    diff_root = D2
    proposer = CN1
  }
  diff_entries = [
    Alice_update,
    Bob_update,
    Emma_update
  ]
}
```

账户叶更新：

- Alice: `head_ref = ref(A2)`, `prev_ref = ref(A1)`
- Bob: `head_ref = ref(B1)`, `prev_ref = NULL`
- Emma: `head_ref = ref(E1)`, `prev_ref = NULL`

### 3.4 高度 2 Receipt

```text
R_A2 = {
  header_lite = (2, H2, S2)
  seq = 2
  prev_ref = ref(A1)
  account_state_proof = pi_A2
}

R_B1 = {
  header_lite = (2, H2, S2)
  seq = 1
  prev_ref = NULL
  account_state_proof = pi_B1
}

R_E1 = {
  header_lite = (2, H2, S2)
  seq = 1
  prev_ref = NULL
  account_state_proof = pi_E1
}
```

对应：

- `U_A2 = (R_A2, B_A2)`
- `U_B1 = (R_B1, B_B1)`
- `U_E1 = (R_E1, B_E1)`

### 3.5 高度 2 后 sender 本地更新

#### Alice 的更新

Alice 在本轮后仍持有的一些值：

- `[100,299]`
- `[350,599]`

它们都是 Alice 在 `B_A2` 前就已持有的值，所以都需要追加 `U_A2`。

因此：

```text
W_A_[100,299] = [U_A2, U_A1]
W_A_[350,599] = [U_A2, U_A1]
```

而被发给 Helen 的 `[300,349]`，其 outgoing witness 是：

```text
W_A_to_H_[300,349] = {
  current_owner = Alice
  confirmed_bundle_chain = [U_A2, U_A1]
  anchor = GenesisAnchor(H0, Alice, [300,599])
}
```

被发给 Carol 的 `[2700,2749]` 则是：

```text
W_A_to_C_[2700,2749] = {
  current_owner = Alice
  confirmed_bundle_chain = [U_A2]
  anchor = PriorWitnessLink(
    acquire_tx = tx_G1_0,
    prior_witness = W_from_Grace_to_Alice
  )
}
```

这两个 witness 明显不同。

#### Bob 的更新

Bob 在本轮后除了把 `[0,99]` 发给 Frank，还仍然持有创世值：

- `[600,899]`
- `[900,1199]`

注意，这两个值虽然没有出现在 `B_B1` 中，但因为 Bob 在高度 2 确实发过一个 Bundle，所以它们未来的合法性证明也必须检查 `B_B1`。

因此，Bob 本地对这两个老值也必须追加：

- `U_B1`

#### Emma 的更新

Emma 把 `[1500,1599]` 发回给 Dave 后，本地仍持有：

- `[2100,2399]`

这类老值同样也要追加 `U_E1`。

### 3.6 高度 2 的四组 P2P 验证

#### A. Alice -> Carol : `[2700,2749]`

Carol 收到：

```text
W_A_to_C_[2700,2749] = {
  current_owner = Alice
  confirmed_bundle_chain = [U_A2]
  anchor = PriorWitnessLink(tx_G1_0, W_G_to_A)
}
```

Carol 必须递归验证：

1. `U_A2`
2. `tx_G1_0` 在 `U_G1.bundle_sidecar` 中确实存在
3. `W_G_to_A` 的链：
   - `confirmed_bundle_chain = [U_G1]`
   - `anchor = GenesisAnchor(H0, Grace, [2700,2999])`

验证通过后，Carol 本地得到：

```text
W_C_[2700,2749] = {
  current_owner = Carol
  confirmed_bundle_chain = []
  anchor = PriorWitnessLink(tx_A2_0, W_A_to_C_[2700,2749])
}
```

#### B. Alice -> Helen : `[300,349]`

Helen 收到的 witness 比 Carol 更长：

```text
confirmed_bundle_chain = [U_A2, U_A1]
anchor = GenesisAnchor(H0, Alice, [300,599])
```

Helen 必须检查：

1. `B_A2` 里确实有 `[300,349]`
2. `R_A2.prev_ref == ref(A1)`
3. `B_A1` 中没有提前花掉 `[300,349]`
4. 创世块确实把 `[300,599]` 分给了 Alice

#### C. Bob -> Frank : `[0,99]`

Frank 收到：

```text
W_B_to_F_[0,99] = {
  current_owner = Bob
  confirmed_bundle_chain = [U_B1]
  anchor = PriorWitnessLink(tx_A1_0, W_A_to_B_[0,99])
}
```

Frank 递归检查：

1. `U_B1` 合法
2. `tx_A1_0` 在 `B_A1` 中存在
3. `U_A1` 合法
4. 创世锚点合法

#### D. Emma -> Dave : `[1500,1599]`

Dave 递归验证：

1. `U_E1`
2. prior witness 指向 `tx_D1_0`
3. `U_D1`
4. 创世锚点

验证通过后，Dave 重新成为 `[1500,1599]` 的 owner。

### 3.7 高度 2 后触发 Checkpoint

由于 `[1500,1599]` 原本来自 Dave，经过：

- `Dave -> Emma`（高度 1）
- `Emma -> Dave`（高度 2）

现在该值又回到了 Dave 手中。

Dave 可以记录：

```text
CP_D_[1500,1599] = {
  value_begin = 1500
  value_end = 1599
  owner_addr = Dave
  checkpoint_height = 2
  checkpoint_block_hash = H2
  checkpoint_bundle_hash = hash(B_E1)
}
```

这个 checkpoint 表示：

- Dave 对 `[1500,1599]` 在高度 2 之前的完整合法历史已经验证过
- 以后若从这个点往后继续流转，只需从 checkpoint 之后开始验证

---

## 4. 高度 3：Checkpoint 生效、长持有值的 witness 增长

### 4.1 高度 3 前的并行用户行为

本轮我们挑两个非常有代表性的交易：

1. `Dave -> Helen : [1500,1599]`
2. `Bob -> Grace : [600,649]`

其意义完全不同：

- Dave 的值刚刚在高度 2 触发过 checkpoint
- Bob 的 `[600,649]` 是从创世块起一直持有到现在的老值

### 4.2 高度 3 Bundle

```text
B_D2 = {
  sender_addr = Dave
  tx_list = [
    tx_D2_0: Dave -> Helen, value=[1500,1599]
  ]
}

B_B2 = {
  sender_addr = Bob
  tx_list = [
    tx_B2_0: Bob -> Grace, value=[600,649]
  ]
}
```

### 4.3 高度 3 出块

本轮 `CN4` 获胜。

账户叶更新：

- Dave: `head_ref = ref(D2)`, `prev_ref = ref(D1)`
- Bob: `head_ref = ref(B2)`, `prev_ref = ref(B1)`

注意：

- Dave 在高度 2 只是“收到了值”
- 这不会更新 Dave 的账户叶
- 只有 Dave 自己在高度 3 提交 `B_D2` 时，Dave 的 sender 叶才会更新

### 4.4 高度 3 Receipt 与 ConfirmedBundleUnit

```text
R_D2 = {
  header_lite = (3, H3, S3)
  seq = 2
  prev_ref = ref(D1)
  account_state_proof = pi_D2
}

R_B2 = {
  header_lite = (3, H3, S3)
  seq = 2
  prev_ref = ref(B1)
  account_state_proof = pi_B2
}
```

对应：

- `U_D2 = (R_D2, B_D2)`
- `U_B2 = (R_B2, B_B2)`

### 4.5 Dave 的 outgoing witness

Dave 现在向 Helen 发送 `[1500,1599]` 时，不必再把从创世到高度 2 的整条链都发一遍。

他可以构造：

```text
W_D_to_H_[1500,1599] = {
  current_owner = Dave
  confirmed_bundle_chain = [U_D2]
  anchor = CheckpointAnchor(CP_D_[1500,1599])
}
```

Helen 只需验证：

1. `U_D2`
2. Checkpoint 是否匹配

这就是 checkpoint 的直接收益。

### 4.6 Bob 的 outgoing witness

Bob 向 Grace 发送 `[600,649]` 时情况完全不同。

这个值从创世块起一直由 Bob 持有到高度 3，中间 Bob 在高度 2 发过 `B_B1`，虽然 `B_B1` 处理的是 `[0,99]`，但 Grace 仍必须确认：

- Bob 在 `B_B1` 中有没有偷偷花掉 `[600,649]`

所以 Bob 发给 Grace 的 witness 必须是：

```text
W_B_to_G_[600,649] = {
  current_owner = Bob
  confirmed_bundle_chain = [U_B2, U_B1]
  anchor = GenesisAnchor(H0, Bob, [600,899])
}
```

这个案例清楚地说明：

- sender 的任意一次 Bundle，都可能让其“长期持有老值”的 witness 继续增长
- 即使该 Bundle 完全没有显式触碰该值

这也是 V2 在复杂度控制上必须重点处理的地方。

### 4.7 高度 3 后 recipient 更新

Helen 接受 `[1500,1599]` 后，得到：

```text
W_H_[1500,1599] = {
  current_owner = Helen
  confirmed_bundle_chain = []
  anchor = PriorWitnessLink(tx_D2_0, W_D_to_H_[1500,1599])
}
```

Grace 接受 `[600,649]` 后，得到：

```text
W_G_[600,649] = {
  current_owner = Grace
  confirmed_bundle_chain = []
  anchor = PriorWitnessLink(tx_B2_0, W_B_to_G_[600,649])
}
```

---

## 5. 高度 4：Receipt 拉取、空当前链转为非空、递归验证继续展开

### 5.1 高度 4 前的并行用户行为

现在有两个 recipient 准备进一步转手新收到的值：

1. `Helen -> Alice : [1500,1599]`
2. `Carol -> Emma : [2700,2749]`

注意：

- Helen 持有 `[1500,1599]` 时，自己的 `confirmed_bundle_chain = []`
- Carol 持有 `[2700,2749]` 时，自己的 `confirmed_bundle_chain = []`

这两个值都来自 prior witness，而不是来自各自本人的已确认历史。

### 5.2 高度 4 Bundle

```text
B_H1 = {
  sender_addr = Helen
  tx_list = [
    tx_H1_0: Helen -> Alice, value=[1500,1599]
  ]
}

B_C1 = {
  sender_addr = Carol
  tx_list = [
    tx_C1_0: Carol -> Emma, value=[2700,2749]
  ]
}
```

### 5.3 高度 4 出块

本轮 `CN2` 获胜，打包：

- `B_H1`
- `B_C1`

叶更新：

- Helen: `head_ref = ref(H1)`, `prev_ref = NULL`
- Carol: `head_ref = ref(C1)`, `prev_ref = NULL`

因为：

- 两人在此之前都没有提交过自己的 Bundle

### 5.4 Receipt 分发中出现一个并行事件

本轮出现一个很真实的轻量设备场景：

- `CN2` 能立刻把 `R_H1` 推送给 Helen
- 但 Carol 短暂离线，没有立刻收到 `R_C1`

于是：

1. `CN2` 将 `R_C1` 写入最近 Receipt 缓存
2. Carol 重连后，通过：

```text
GetReceipt(addr=Carol, seq=1)
```

从任意共识节点拉取到 `R_C1`

这证明：

- “推送优先，拉取兜底”的机制在真实运行中确实有必要

### 5.5 高度 4 P2P 验证

#### A. Helen -> Alice : `[1500,1599]`

Alice 收到：

```text
W_H_to_A_[1500,1599] = {
  current_owner = Helen
  confirmed_bundle_chain = [U_H1]
  anchor = PriorWitnessLink(
    acquire_tx = tx_D2_0,
    prior_witness = W_D_to_H_[1500,1599]
  )
}
```

Alice 验证时递归展开：

1. `U_H1`
2. `tx_D2_0`
3. `W_D_to_H_[1500,1599]`
4. 其中又包含：
   - `confirmed_bundle_chain = [U_D2]`
   - `anchor = CheckpointAnchor(CP_D_[1500,1599])`

也就是说，这条验证链已经被 checkpoint 压缩成：

```text
Helen current segment -> Dave current segment -> Checkpoint
```

而不再是：

```text
Helen -> Dave -> Emma -> Dave -> Genesis
```

#### B. Carol -> Emma : `[2700,2749]`

Emma 收到：

```text
W_C_to_E_[2700,2749] = {
  current_owner = Carol
  confirmed_bundle_chain = [U_C1]
  anchor = PriorWitnessLink(
    acquire_tx = tx_A2_0,
    prior_witness = W_A_to_C_[2700,2749]
  )
}
```

Emma 递归验证：

1. `U_C1`
2. `tx_A2_0`
3. `W_A_to_C_[2700,2749] = [U_A2] + prior_witness_from_Grace`
4. `prior_witness_from_Grace = [U_G1] + GenesisAnchor`

这条链没有 checkpoint，因此仍较长。

---

## 6. 通过案例暴露出的协议问题

下面列出本次推演真正暴露出来的问题。这些问题并不是抽象担忧，而是在上述 4 个高度的真实数据流中已经出现了。

### 问题 1：Receipt 到账后的“追加范围”定义不够严密

在当前 draft 的表述里，sender 收到 Receipt 后似乎只需要更新“相关 Value”。

但在本案例中：

- Alice 的 `B_A1` 没有触碰 `[300,599]`
- Bob 的 `B_B1` 没有触碰 `[600,899]`

然而未来 recipient 仍必须检查这些 Bundle。

所以真正正确的规则应是：

> sender 的新 `ConfirmedBundleUnit`，必须追加到“所有在该 Bundle 确认之前已经由 sender 持有、且在 Bundle 确认后仍继续由 sender 持有”的 Value/Witness 上。

修改建议：

1. 修改 draft 的 `14.1/14.2`
2. 把“涉及的 Value”改成“所有 acquisition_boundary 早于本次 Bundle 的在持值”
3. 明确区分：
   - 长期持有老值：要追加
   - 本轮刚收到、此前不归 sender 持有的值：不追加旧 Bundle

### 问题 2：必须显式定义 acquisition boundary

Carol 验证 `[2700,2749]` 时，Alice 的当前段只有 `[U_A2]`，不包含 `U_A1`。

这并不是缺失，而是因为：

- Alice 在高度 1 之后才从 Grace 收到该值
- 所以该值的 sender-history 起点是“获得时刻”，不是 Alice 全部 sender-history 的起点

如果协议不显式定义 acquisition boundary，实现者很容易误以为：

- 只要某 sender 有更老的 Bundle，就一律都要放进当前值的 sender-history

这会导致 Witness 冗余膨胀。

修改建议：

1. 在 draft 的 WitnessV2 一节中增加 `acquisition_boundary` 概念说明
2. 明确：
   - `confirmed_bundle_chain` 只覆盖“当前 owner 自获得该值以来”的 sender Bundle
   - 链首单元的 `prev_ref` 可以指向 acquisition_boundary 之前的旧 Bundle，这不构成错误

### 问题 3：当前 TransferPackage 语义仍然太“胖”

本案例里，Alice 在高度 2 的同一个 Bundle `B_A2` 中向 Carol 和 Helen 同时转账。

这意味着：

- Carol 需要拿到 `U_A2`
- Helen 也需要拿到 `U_A2`
- Alice 本地持有的多个剩余值也都引用 `U_A2`

如果实现层直接把完整递归 Witness 按 Value 复制发送，就会出现严重重复传输与重复存储。

修改建议：

1. 在 draft 中明确：
   - `TransferPackage` 在实现层 SHOULD 采用对象去重
   - `ConfirmedBundleUnit` 应按 `bundle_hash` 共享存储
2. 增加一个可选的“两阶段传输”方案：
   - 第一阶段：发送 `tx + witness summary`
   - 第二阶段：recipient 按需请求缺失的 `ConfirmedBundleUnit`
3. 在轻量设备默认实现中，优先发送：
   - 目标值必须的最短链
   - 已有单元不重复发送

### 问题 4：BundleSidecar 的本地持久化与回收规则还不够明确

最小 Receipt 设计成立的前提是：

- sender 自己保留了原始 `BundleSidecar`

但从案例可以看到：

- `B_A1` 在高度 1 生成
- 到高度 2，Helen 验证 `[300,349]` 时仍需要 `B_A1`
- 到更后面的递归链中，它甚至可能继续存在

所以“收到 Receipt 后即可删除旧 Sidecar”是错误的。

修改建议：

1. 明确 sender 在提交 Bundle 前必须把 `BundleSidecar` 落盘
2. 在 draft 中增加本地 GC 规则：
   - `BundleSidecar` 只有在不存在任何活跃 Value/Witness 引用时才可删除
3. 推荐实现：
   - `bundle_hash -> BundleSidecar` 对象库
   - 引用计数或可达性扫描
4. 可选增加紧急恢复接口：
   - `GetBundleSidecarByHash(bundle_hash)`
   - 仅作异常恢复，不作为常规路径

### 问题 5：Checkpoint 对 split / partial return 的语义还不清晰

本案例中的 checkpoint 是 exact-match：

- `[1500,1599]` 从 Dave 出去，又完整回到 Dave

这很好处理。

但若下一轮 Helen 只把 `[1500,1549]` 返还给 Dave，那么：

- Dave 能否部分复用 `CP_D_[1500,1599]`？

当前 draft 未给出精确规则。

修改建议：

1. MVP 版本先只支持 exact-range checkpoint
2. 即：
   - `Checkpoint` 只对完全相同的 `value_begin/value_end` 生效
3. partial overlap / containment 的 checkpoint 复用留到 V2.x
4. 若未来要支持部分复用，必须先定义：
   - 值分裂后的规范继承规则
   - checkpoint 与子区间映射规则

### 问题 6：Value 状态机还需要更细

本案例里有至少三种不同状态：

1. Bob 在高度 1 接收 `[0,99]` 并验证成功后，尚未有自己的 confirmed chain，但它已经是可花费的
2. Carol 在高度 4 之前提交了 `B_C1`，但短暂离线，Receipt 未立刻到账
3. Carol 重连拉取到 Receipt 后，才真正可以把 `U_C1` 追加进本地链

这说明简单的：

- `SPENDABLE`
- `PENDING_BUNDLE`
- `RECEIPT_MISSING`

还不够表达真实语义。

修改建议：

1. 增加或细化状态：
   - `VERIFIED_SPENDABLE`
   - `PENDING_CONFIRMATION`
   - `RECEIPT_PENDING`
   - `UNFINALIZED_RECEIVED`
2. 明确：
   - recipient 验证通过后、尚未自行出过块的值，也属于可花费值
   - 但其 `confirmed_bundle_chain` 为空

### 问题 7：mempool 快照边界和“并行事件切分点”需要协议化

本案例中，用户提交、Receipt 推送、P2P 验证、leader 竞争其实是并行发生的。

若协议不定义：

- 某个高度的 mempool 快照截止点
- 晚到 Bundle 进入下一高度的规则

则不同共识节点可能因为接收时间差异打出不同候选块。

修改建议：

1. 在 draft 的出块章节中加入：
   - `snapshot_cutoff_time`
   - `proposal_round_id`
2. 明确：
   - 截止点之后到达的 Bundle 自动滚入下一轮
3. 这样才能让“并行事件”与“单高度候选块”兼容

### 问题 8：钱包选值策略必须进入协议建议层

本案例里：

- Bob 在高度 3 发送 `[600,649]`
- 由于这是创世老值，Witness 明显变长

而 Bob 若优先花掉“新近获得且历史短”的值，成本会更低。

这与 VWchain-V1 附录里的 value selection 优化思想是一致的。

修改建议：

1. 在 draft 的用户提交流程中增加钱包策略建议：
   - 优先使用最新获得值
   - 优先使用能触发 checkpoint 的值
   - 尽量避免长期持有值继续累积 sender-history
2. 将其标为 `SHOULD` 级建议，而不是交给实现完全自由决定

---

## 7. 建议如何修改现有 draft

下面给出对 [EZchain-V2-protocol-draft.md](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZchain-V2-design/EZchain-V2-protocol-draft.md) 的具体修改建议。

### 7.1 修改 `14.1 / 14.2`

把当前“收到 Receipt 后更新相关 Value”的表述，改成更严格的版本：

```text
当 sender 的 Bundle 在高度 h 被确认后，
新 ConfirmedBundleUnit 必须追加到所有满足以下条件的本地 Value/Witness：
1. 该 Value 在高度 h 之前已经归 sender 持有；
2. 该 Value 在该 Bundle 执行后仍归 sender 持有，或将以该 Bundle 作为其对外转移的最后一跳；
3. 该 Value 的 acquisition_boundary 早于高度 h。
```

### 7.2 修改 `5.10 / 15.3`

在 Witness 和验证算法中补充 acquisition boundary：

```text
confirmed_bundle_chain 仅覆盖当前 owner 自 acquisition_boundary 以来的 sender Bundle。
链首单元的 prev_ref 可以指向 acquisition_boundary 之前的 sender 旧 Bundle，
验证者不应据此认定 witness 缺失。
```

### 7.3 在 Receipt 章节后新增“本地对象库与 GC”小节

建议新增：

1. `BundleObjectStore`
2. `bundle_hash -> BundleSidecar`
3. 引用计数或可达性回收规则
4. `BundleSidecar` 提交前持久化要求

### 7.4 在 P2P 章节增加“去重传输 / 按需拉取”建议

建议新增可选机制：

```text
TransferSummary {
  target_tx
  target_value
  root_witness_id
  missing_unit_ids
}
```

recipient 若缺少某些 `ConfirmedBundleUnit`，再按 `bundle_hash` 拉取。

### 7.5 在 Checkpoint 章节明确 MVP 范围

建议补一句：

> V2 MVP 版本仅支持 exact-range checkpoint，不支持部分区间复用。

### 7.6 在状态章节增加更细粒度状态

建议把状态机调整为至少：

- `SPENDABLE`
- `VERIFIED_SPENDABLE`
- `PENDING_BUNDLE`
- `PENDING_CONFIRMATION`
- `RECEIPT_PENDING`
- `RECEIPT_MISSING`
- `LOCKED_FOR_VERIFICATION`
- `ARCHIVED`

### 7.7 在出块章节补充 mempool 快照边界

建议新增：

```text
每个高度 h 的候选块只从 round(h) 的 mempool snapshot 中取 Bundle。
snapshot_cutoff 之后到达的 Bundle 自动进入 round(h+1)。
```

### 7.8 在用户提交流程加入 value selection 建议

建议新增一句：

> 钱包 SHOULD 优先选择 witness 较短的值、可触发 checkpoint 的值、或最新获得的值，以控制后续 P2P 验证成本。

---

## 8. 结论

通过这个 4 共识节点、8 用户节点、4 个区块高度的连续案例，可以确认：

1. `单根状态树 + diff_root + sender 历史递归验证 + checkpoint 裁剪` 这条路线总体上是可运行的。
2. 最小 Receipt 设计是对的，而且对轻量设备很重要。
3. 但当前 draft 仍有几个必须补齐的“协议级细节”：
   - Receipt 到账后的更新范围
   - acquisition boundary
   - `BundleSidecar` 的持久化与 GC
   - checkpoint 的 exact-match 边界
   - 钱包选值策略
   - 并行 mempool 快照边界

如果这些点补上，V2 的工程可落地性会明显提高，而且很多后续实现争议可以在协议层提前消解。
