# EZchain V2 共识 MVP 规格草案

## 0. 文档目的

本文件只解决一件事：

> 在 EZchain V2 中，真正的共识层到底采用哪条路线。

当前仓库已经有：

- `BundleEnvelope / BundleSidecar`
- `DiffEntry / DiffPackage / diff_root`
- `state_root`
- `Receipt / prev_ref`
- 本地与 TCP 形式的 V2 节点骨架

但当前“共识节点”仍主要是：

- 本地打包
- 广播区块
- 跟随节点验块后追平

它还不是一个完整的正式共识协议。

因此，在开始写真正的共识代码前，必须先把下面这些问题固定下来：

- 用什么 BFT 路线
- VRF 到底用在什么地方
- leader 如何选
- 投票如何做
- 什么时刻才算最终确认
- 什么时刻才允许分发 Receipt
- 超时后如何换轮

本文件是后续共识实现、测试、文档和审查的上位约束。

---

## 1. 结论先固定

EZchain V2 共识 MVP 采用：

- **Algorand 式 VRF 随机选 proposer**
- **HotStuff 风格三阶段 BFT 确认**

明确不采用：

- 经典 `PBFT`
- 第一版就完整照搬 `Algorand BA*`

更直白地说：

- **谁来提议区块，用 VRF 随机选**
- **区块怎么被正式确认，用 HotStuff 风格投票**

---

## 2. 为什么这样选

## 2.1 为什么不用经典 PBFT

PBFT 的问题不是“不能工作”，而是对 EZchain V2 当前阶段不够合适：

1. 消息流程偏重，节点规模一大开销明显上升。
2. leader 故障后的 view-change 工程复杂度较高。
3. 不够适合后续从“小规模固定节点”走向“更多候选共识节点”的方向。
4. 和当前仓库已存在的 `DiffPackage + QC-like justify` 演化方向不够顺。

因此，PBFT 不作为 V2 的默认正式路线。

## 2.2 为什么不直接做完整 Algorand BA*

完整 Algorand BA* 很强，但第一版直接照搬风险太高。

它真正复杂的地方不只是 VRF，而是整套一起出现：

- 提议者 sortition
- 不同步骤的随机委员会
- soft vote
- certify vote
- recovery mode
- 轮次间随机种子演进
- stake 权重与委员会大小计算

在 EZchain 当前状态下，如果把这些一步到位实现，协议风险和实现风险都会显著上升。

## 2.3 为什么选“VRF + HotStuff”

这条路线对 EZchain V2 最现实：

1. 和现有设计兼容：
   - `DiffPackage`
   - `state_root`
   - `diff_root`
   - `Receipt`
2. 和已有小规模推演方向一致：
   - 每轮 leader
   - 其他共识节点验证并投票
   - 达阈值后最终确认
3. 比 PBFT 更适合 leader 轮换与后续扩展。
4. 比完整 Algorand BA* 更容易先做出一个严谨、可测、可审查的第一版。

---

## 3. MVP 的核心选择

为了保证第一版安全边界清楚，MVP 采用下面这些固定选择。

## 3.1 当前只用 VRF 选 proposer，不用 VRF 选投票委员会

这是本文件最重要的工程决定之一。

MVP 中：

- **VRF 只负责 proposer 选择**
- **投票使用完整共识节点集合**

也就是说，第一版不是：

- “随机抽一小撮节点出来投票”

而是：

- “随机决定这一轮谁来提议”
- “所有合法共识节点都参与 BFT 投票”

这样做的原因很明确：

1. 这样最接近 HotStuff 的标准安全边界。
2. 不需要现在就解决“随机委员会交叉性”的完整证明问题。
3. 不需要现在就引入 stake 权重、委员会大小估算、sortition 误差这些高风险问题。

这一步是为了先把协议做对，而不是先把规模做大。

### 3.1.1 当前代码里的过渡实现边界

这里必须额外说明一件事：

- **当前仓库代码里还没有正式的学术规范 VRF 实现**
- 当前只允许存在一种**过渡态的签名式 proposer claim**
- 这套过渡态只能用于开发联调和接口收口
- **不能把它当成正式 VRF 已完成**

更直白地说：

- 现在代码里可以先用共识节点自己的 `vrf_key` 对 sortition message 做签名
- 再从该签名导出一个可验证的 proposer claim
- 这样能先把“谁来提议、别人怎么验这个 claim”这条接口跑通

但这仍然不是正式 VRF。

所以后续对外口径必须保持为：

- `proposer sortition` 接口和验证流程已经开始落地
- **正式 VRF 密码学实现仍是后续必做项**

## 3.2 共识节点集合先固定，采用许可型 validator set

MVP 默认采用：

- 固定共识节点集合
- 每个共识节点 1 票
- `n = 3f + 1`
- 法定阈值为 `2f + 1`

当前不做：

- 无许可开放加入
- stake 权重
- 动态 validator rotation

原因很简单：

- VRF 本身不解决女巫攻击
- 如果不先固定谁有资格参与，随机选举就没有安全基础

因此，MVP 先做“许可型、等权重”的版本。

### 3.2.1 这不是“随手改的中心化白名单”

这里必须把边界说死。

MVP 的 validator set 虽然是许可型，但**不应实现成一个节点本地随时可改的中心化 allowlist 文件**。

正确做法应当是：

1. 当前 epoch 的 validator set 在创世时就固定下来。
2. 该集合要有一个确定性的 `validator_set_hash`。
3. 所有共识节点对同一个 `validator_set_hash` 达成一致。
4. proposer 资格和投票资格都只对该集合中的成员开放。

也就是说：

- 不是“谁机器上多写几个地址，谁就能参与 VRF”
- 也不是“运维临时改本地配置，就算合法共识节点”

MVP 推荐来源：

- 创世配置中的 `consensus_validators`

并要求至少包含：

- `validator_id`
- `consensus_vote_pubkey`
- `vrf_pubkey`
- `weight`

虽然 MVP 先做等权重，但 `weight` 字段建议保留，后续升级不会更痛。

### 3.2.2 validator set 如何进入协议

MVP 中，proposal 和 vote 的合法性必须绑定到当前 epoch 的 validator set。

因此每个共识节点在验证 proposal / vote 时，必须同时确认：

1. `proposer_id` 属于当前 validator set
2. proposal 中的 `vrf_proof` 对应该 proposer 的 `vrf_pubkey`
3. vote 的签名对应该 validator 的 `consensus_vote_pubkey`
4. 当前消息声明的 `epoch_id` 和本地一致
5. 当前消息声明的 `validator_set_hash` 和本地一致

### 3.2.3 validator set 更新不在当前 MVP

MVP 明确不做：

- 动态增删 validator
- 链上 stake 驱动的 validator 更新
- 任意高度即时切换 validator set

MVP 中默认：

- `epoch_id = 0`
- `validator_set_hash` 在创世后固定

后续如果要扩展，推荐路线是：

- 只允许在 epoch 边界变更 validator set
- 由一类特殊治理交易或治理证书触发
- 新集合从下一个 epoch 生效

而不是运行中直接热改本地白名单。

## 3.3 不做 pipelined chained HotStuff

MVP 采用：

- **非流水线**
- **按高度逐块确认**
- **显式三阶段**

不采用第一版就做：

- chained HotStuff 的流水化实现

原因：

1. 更容易写清楚状态机。
2. 更容易做故障测试和代码审查。
3. 更适合当前仓库从“复制式演练”过渡到“正式共识”。

---

## 4. 共识参与者与密钥

每个共识节点在 MVP 中至少有三类身份材料：

1. `node_id`
   - 网络与运维层标识
2. `consensus_vote_key`
   - 用于共识消息签名
3. `vrf_key`
   - 用于 proposer sortition

MVP 要求：

- `consensus_vote_key` 和 `vrf_key` 不得混用
- 用户钱包私钥不得承担共识签名职责

后续如需更接近 Algorand，可再引入：

- epoch 参与密钥
- 更细粒度的临时投票密钥

但这不是 MVP 的前置条件。

### 4.1 和应用层钱包密钥彻底分离

V2 中必须严格区分三类密钥：

1. 用户钱包密钥
   - 给 `BundleEnvelope` 签名
2. 共识投票密钥
   - 给 vote、timeout vote、QC 相关对象签名
3. VRF 密钥
   - 只用于 proposer sortition

任何实现如果把这三类密钥混在一起，都会给后续安全审查制造大坑。

---

## 5. 轮次、视图与随机种子

## 5.1 时间单位

定义两个基本单位：

- `height`
  - 要确认的区块高度
- `round`
  - 同一高度下的 leader 尝试轮次

同一高度 `h` 下，可能会经历：

- `round = 1, 2, 3, ...`

直到某个提议被最终确认。

## 5.2 随机种子

MVP 中，每个高度使用一个确定性随机种子 `seed_h`。

建议定义：

```text
seed_{h+1} = H(
  "EZCHAIN_V2_SEED"
  || seed_h
  || commit_qc.block_hash
  || winning_vrf_output
)
```

要求：

1. `seed_h` 必须在高度 `h` 最终确认后才能确定。
2. 下一高度的 proposer 选择只能使用已最终确认的前序种子。
3. 节点不得使用本地时间或未确认块哈希作为 proposer 选举输入。

这样做的目的，是让 proposer 选择既可验证，又尽量避免被提前操纵。

---

## 6. Proposer 选举

## 6.1 输入

对高度 `h`、轮次 `r`，每个合法共识节点计算：

```text
vrf_input = H(
  "EZCHAIN_V2_PROPOSER"
  || chain_id
  || epoch_id
  || height
  || round
  || seed_h
)
```

然后本地运行 VRF：

```text
(vrf_output, vrf_proof) = VRF(vrf_key, vrf_input)
```

## 6.2 资格规则

MVP 中 proposer 选择采用“阈值 + 最小 credential 胜出”的规则：

1. 所有 validator 都本地自选。
2. 若 `vrf_output < proposer_threshold`，则该节点有资格提议。
3. 若同一轮有多个合法 proposer，则：
   - 取 `vrf_output` 最小者作为本轮 winner。
4. 若超时前没有看到合法 proposer，则进入下一轮。

## 6.3 为什么这样做

这保留了 Algorand 式的“本地可验证自选”优点，同时避免把第一版复杂度推到完整 BA*。

### 6.4 创世 validator set 配置格式

为了避免后面每层都各自发明一套配置表示，MVP 先固定创世格式。

推荐结构：

```text
ConsensusValidator {
  validator_id: string
  consensus_vote_pubkey: bytes
  vrf_pubkey: bytes
  weight: uint64
}
```

```text
ConsensusGenesisConfig {
  chain_id: uint64
  epoch_id: uint64          // MVP 固定为 0
  validators: [ConsensusValidator]
}
```

约束：

1. `validator_id` 全局唯一
2. `consensus_vote_pubkey` 全局唯一
3. `vrf_pubkey` 全局唯一
4. MVP 中所有 `weight = 1`
5. validators 按 `validator_id` 排序后再做哈希和签名输入

### 6.5 `validator_set_hash` 计算规则

`validator_set_hash` 必须是确定性的。

推荐定义：

```text
validator_set_hash = H(
  "EZCHAIN_V2_VALIDATOR_SET"
  || canonical_encode(
       epoch_id,
       [
         (validator_id, consensus_vote_pubkey, vrf_pubkey, weight),
         ...
       ]
     )
)
```

要求：

1. validators 先按 `validator_id` 严格排序
2. 不允许同一集合出现重复 validator
3. `weight` 虽然当前固定为 1，但也必须纳入哈希

这样后续即使引入权重，也不会推翻哈希规则。

---

## 7. BFT 确认算法

## 7.1 总体路线

MVP 采用 **HotStuff 风格三阶段确认**：

1. `PREPARE`
2. `PRECOMMIT`
3. `COMMIT`

当 `COMMIT` 阶段形成有效 `CommitQC` 时，该块在该高度最终确认。

## 7.2 阈值

设 validator 总数为 `n = 3f + 1`。

则：

- 任一阶段形成 QC 需要至少 `2f + 1` 个有效投票。

MVP 中每个 validator 只有 1 票。

## 7.3 消息对象

MVP 至少需要下面这些共识消息：

### Proposal

```text
Proposal {
  height
  round
  proposer_id
  vrf_output
  vrf_proof
  block_header
  diff_package
  justify_qc
  proposer_sig
}
```

#### Proposal 字段表

| 字段 | 类型 | 必填 | 进入签名 | 说明 |
| --- | --- | --- | --- | --- |
| `chain_id` | `uint64` | 是 | 是 | 网络标识 |
| `epoch_id` | `uint64` | 是 | 是 | 当前 validator epoch |
| `validator_set_hash` | `bytes32` | 是 | 是 | 绑定当前合法 validator 集 |
| `height` | `uint64` | 是 | 是 | 当前目标高度 |
| `round` | `uint64` | 是 | 是 | 当前轮次 |
| `proposer_id` | `string` | 是 | 否 | proposer 身份索引 |
| `vrf_output` | `bytes` | 是 | 是 | sortition 结果 |
| `vrf_proof` | `bytes` | 是 | 否 | sortition 证明材料 |
| `block_header` | `BlockHeaderV2` | 是 | 通过 `block_hash` 绑定 | 区块头 |
| `diff_package` | `DiffPackage` | 是 | 通过 `block_hash` 绑定 | 区块差异主体 |
| `justify_qc` | `QC or TC-derived highest_qc` | 是 | 通过 `justify_qc_hash` 绑定 | 本轮安全锚点 |
| `proposer_sig` | `bytes` | 是 | - | proposer 签名 |

### Vote

```text
Vote {
  phase        // PREPARE | PRECOMMIT | COMMIT
  height
  round
  voter_id
  block_hash
  justify_qc_hash
  voter_sig
}
```

#### Vote 字段表

| 字段 | 类型 | 必填 | 进入签名 | 说明 |
| --- | --- | --- | --- | --- |
| `chain_id` | `uint64` | 是 | 是 | 网络标识 |
| `epoch_id` | `uint64` | 是 | 是 | 当前 epoch |
| `validator_set_hash` | `bytes32` | 是 | 是 | 绑定 validator 集 |
| `phase` | `enum` | 是 | 是 | `PREPARE / PRECOMMIT / COMMIT` |
| `height` | `uint64` | 是 | 是 | 当前高度 |
| `round` | `uint64` | 是 | 是 | 当前轮次 |
| `voter_id` | `string` | 是 | 否 | 投票者身份索引 |
| `block_hash` | `bytes32` | 是 | 是 | 当前投票目标块 |
| `justify_qc_hash` | `bytes32` | 是 | 是 | proposal 携带的 `justify_qc` 摘要 |
| `voter_sig` | `bytes` | 是 | - | validator 投票签名 |

### QuorumCertificate

```text
QC {
  phase
  height
  round
  block_hash
  signer_ids
  signatures
}
```

MVP 中允许：

- 直接携带 `2f + 1` 份签名

后续再优化为聚合签名。

### 7.3.1 每类消息的签名覆盖范围

这一点必须先定清楚，否则后面很容易出现“字段加了，但没进签名”的安全漏洞。

规则固定如下：

#### Proposal 的 proposer 签名必须覆盖

- `chain_id`
- `epoch_id`
- `validator_set_hash`
- `height`
- `round`
- `block_hash`
- `justify_qc_hash`
- `vrf_output`

如果 proposal 里有：

- `block_header`
- `diff_package`

则其签名覆盖对象应当是：

- `block_hash`

而不是把整份 `diff_package` 再重复签一次。

原因：

- `block_hash` 已由 `block_header + diff_package` 唯一绑定
- 避免同一语义对象多处重复签名

#### Vote 的 voter 签名必须覆盖

- `chain_id`
- `epoch_id`
- `validator_set_hash`
- `phase`
- `height`
- `round`
- `block_hash`
- `justify_qc_hash`

#### TimeoutVote 的签名必须覆盖

- `chain_id`
- `epoch_id`
- `validator_set_hash`
- `height`
- `round`
- `highest_qc_hash`

#### QC / TC 本身

QC / TC 本身在 MVP 中不单独再签一个“聚合对象签名”，而是：

- 以 `2f + 1` 份原始签名作为合法性依据

后续如果升级聚合签名，再把 QC / TC 自身对象签名规范单独引入。

### 7.3.2 必须做域分离

以下共识对象的签名输入必须带不同的 `domain_separator`：

- `EZCHAIN_V2_PROPOSAL`
- `EZCHAIN_V2_VOTE`
- `EZCHAIN_V2_TIMEOUT_VOTE`

禁止：

- proposal 和 vote 复用同一个签名域
- 让共识签名和用户钱包 bundle 签名共用同一个域

### TimeoutVote / TimeoutCertificate

```text
TimeoutVote {
  height
  round
  voter_id
  highest_qc_hash
  voter_sig
}
```

#### TimeoutVote 字段表

| 字段 | 类型 | 必填 | 进入签名 | 说明 |
| --- | --- | --- | --- | --- |
| `chain_id` | `uint64` | 是 | 是 | 网络标识 |
| `epoch_id` | `uint64` | 是 | 是 | 当前 epoch |
| `validator_set_hash` | `bytes32` | 是 | 是 | 绑定 validator 集 |
| `height` | `uint64` | 是 | 是 | 当前高度 |
| `round` | `uint64` | 是 | 是 | 发生超时的轮次 |
| `voter_id` | `string` | 是 | 否 | 超时投票者 |
| `highest_qc_hash` | `bytes32` | 是 | 是 | 当前已知最高 QC 摘要 |
| `voter_sig` | `bytes` | 是 | - | timeout vote 签名 |

```text
TC {
  height
  round
  signer_ids
  signatures
  highest_qc
}
```

## 7.4 与 `relab/hotstuff` 的实现分层对齐

参考 `relab/hotstuff` 的实现思路，EZchain V2 的共识实现也应拆成至少四层，而不是写成一个“大循环”：

1. `Core / Rules`
   - 只负责：
     - proposal 是否可投
     - block 是否可 commit
     - safety rule
2. `Pacemaker / Synchronizer`
   - 只负责：
     - round 超时
     - 进入下一轮
     - 处理 timeout vote / TC
3. `Crypto / QC`
   - 只负责：
     - vote 签名验证
     - QC / TC 组装与校验
4. `Leader Selection`
   - 在 EZchain 中由：
     - VRF proposer sortition
   - 替代普通 HotStuff 中固定 leader / round-robin 的部分

这四层必须分开，原因很简单：

- 共识规则和超时逻辑不能缠在一起
- VRF 选举不能混进 QC 校验代码里
- 后续升级委员会机制时，才不会推翻整层实现

这也是为什么本方案虽然采用 HotStuff 风格确认层，但实现上不会照抄一个“固定 leader 的 HotStuff demo”。

---

## 8. 单轮状态机

对高度 `h` 的单个 round，状态机如下。

## 8.1 Proposal 阶段

1. 节点根据 `seed_h` 和 `round=r` 本地计算 proposer sortition。
2. 合法 proposer 构造：
   - `BlockHeader`
   - `DiffPackage`
   - `justify_qc`
3. proposer 广播 `Proposal`。
4. 其他节点在 proposal timeout 内收集并比较所有合法 proposal。
5. 若有多个 proposal，保留 `vrf_output` 最小的那个。

## 8.2 Prepare 阶段

每个 validator 对收到的候选 proposal 做检查：

1. proposer 的 VRF proof 合法。
2. proposer 身份属于当前 epoch validator set。
3. `BlockHeader + DiffPackage` 协议合法。
4. `DiffPackage` 对本地旧状态应用后确实得到 `state_root`。
5. `diff_root` 可重算。
6. proposal 满足 safety rule。

若通过，则发送 `PREPARE` 投票。

当收到 `2f + 1` 份 `PREPARE` 投票后，形成 `PrepareQC`。

## 8.3 PreCommit 阶段

收到 `PrepareQC` 后，validator 若仍满足 safety rule，则发送 `PRECOMMIT` 投票。

当收到 `2f + 1` 份 `PRECOMMIT` 投票后，形成 `PreCommitQC`。

## 8.4 Commit 阶段

收到 `PreCommitQC` 后，validator 若仍满足 safety rule，则发送 `COMMIT` 投票。

当收到 `2f + 1` 份 `COMMIT` 投票后，形成 `CommitQC`。

此时：

- 该区块在高度 `h` 最终确认
- 本地链状态推进
- 才允许对 sender 分发 Receipt

### 8.5 Proposal 需要带的共识元数据

为了让节点能独立判断 proposal 是否属于当前合法共识上下文，proposal 至少还必须带：

- `epoch_id`
- `validator_set_hash`
- `highest_qc`
- `locked_qc_ref` 或等价安全锚点

MVP 中若当前区块头结构还放不下这些字段，可以先放入：

- `consensus_extra`

但语义上它们属于正式共识元数据，不应长期躲在“临时扩展字段”里。

### 8.6 Proposal 与 Block 的绑定规则

后续实现时必须保证：

1. `Proposal.block_header.block_hash` 唯一绑定 `diff_package`
2. `Vote.block_hash` 必须就是当前 proposal 的 `block_hash`
3. `justify_qc_hash` 必须绑定 proposal 里实际携带的 `justify_qc`
4. 节点不得对“同一 block_hash、不同 justify_qc”的 proposal 混淆处理

最稳的做法是把 proposal 看成：

- `Proposal = ConsensusEnvelope + BlockCandidate`

其中：

- `ConsensusEnvelope`
  - 负责：
    - `height`
    - `round`
    - `epoch_id`
    - `validator_set_hash`
    - `justify_qc`
    - `vrf_output`
    - `vrf_proof`
- `BlockCandidate`
  - 负责：
    - `block_header`
    - `diff_package`

这样网络层和持久化层都更容易拆清。

### 8.7 单轮状态转移表

为了避免后续实现把“消息处理顺序”和“状态推进”写乱，MVP 先固定最小状态转移表。

| 当前状态 | 输入事件 | 条件 | 输出动作 | 下一状态 |
| --- | --- | --- | --- | --- |
| `ROUND_START` | 本地进入轮次 | - | 计算 proposer sortition，启动 proposal timer | `PROPOSAL_WAIT` |
| `PROPOSAL_WAIT` | 收到合法 proposal | proposal 通过基础校验与 safety rule | 记录候选 proposal | `PROPOSAL_READY` |
| `PROPOSAL_WAIT` | proposal timeout | 未见合法 proposal | 发送 `TimeoutVote` | `TIMEOUT_WAIT` |
| `PROPOSAL_READY` | 本地选择 winner proposal | 选出最优 `vrf_output` | 发送 `PREPARE` vote | `PREPARE_WAIT` |
| `PREPARE_WAIT` | 收到足够 `PREPARE` votes | 达到 `2f+1` | 组装 `PrepareQC`，发送 `PRECOMMIT` vote | `PRECOMMIT_WAIT` |
| `PREPARE_WAIT` | prepare timeout | 未形成 `PrepareQC` | 发送 `TimeoutVote` | `TIMEOUT_WAIT` |
| `PRECOMMIT_WAIT` | 收到足够 `PRECOMMIT` votes | 达到 `2f+1` | 组装 `PreCommitQC`，发送 `COMMIT` vote | `COMMIT_WAIT` |
| `PRECOMMIT_WAIT` | precommit timeout | 未形成 `PreCommitQC` | 发送 `TimeoutVote` | `TIMEOUT_WAIT` |
| `COMMIT_WAIT` | 收到足够 `COMMIT` votes | 达到 `2f+1` | 组装 `CommitQC`，本地 final、更新链状态、发 Receipt | `DECIDED` |
| `COMMIT_WAIT` | commit timeout | 未形成 `CommitQC` | 发送 `TimeoutVote` | `TIMEOUT_WAIT` |
| `TIMEOUT_WAIT` | 收到足够 `TimeoutVote` | 达到 `2f+1` | 组装 `TC`，推进到下一轮 | `ROUND_START(next_round)` |
| `任意` | 收到更高 round 的 `QC / TC` | 本地验证通过且 round 更高 | 更新本地 `highest_qc / highest_tc`，跳轮 | `ROUND_START(higher_round)` |

---

## 9. Safety Rule

每个 validator 必须维护：

- `highest_qc`
- `locked_qc`
- `last_voted_round[(height, phase)]`

最小 safety rule 固定为：

1. 同一 `(height, round, phase)` 不得重复投不同块。
2. 只有 proposal 携带的 `justify_qc` 不低于本地 `locked_qc`，或 proposal 直接延伸自 `locked_qc.block_hash` 时，才允许投票。
3. 一旦 `PreCommitQC` 形成，本地 `locked_qc` 至少推进到该块。
4. `CommitQC` 一旦形成，该块立即 final，不允许再为同高度其他块投票。

这部分必须在代码里显式保存，不能只靠内存临时判断。

---

## 10. 超时与换轮

## 10.1 超时条件

以下任一情况超时，都进入下一轮：

1. proposal timeout 内没有收到合法 proposal
2. prepare timeout 内没有形成 `PrepareQC`
3. precommit timeout 内没有形成 `PreCommitQC`
4. commit timeout 内没有形成 `CommitQC`

## 10.2 TimeoutVote

节点超时后广播：

- `TimeoutVote(height, round, highest_qc_hash, sig)`

当某轮 timeout 收集到 `2f + 1` 个 `TimeoutVote` 后，形成 `TC`。

## 10.3 下一轮提议

下一轮 proposer 构造 `Proposal(height, round+1, ...)` 时必须携带：

- `highest_qc` 或 `TC.highest_qc`

这样下一轮不会丢掉已知的最好安全锚点。

### 10.4 Pacemaker 必须独立可测

这部分实现时必须单独测，不能只靠端到端测试顺带覆盖。

最低要求：

1. proposal timeout 触发正确
2. prepare / precommit / commit timeout 触发正确
3. 收到更高 `QC / TC` 后可以提前推进 round
4. 不会因为重复 timeout 消息导致回退

这是 HotStuff 系实现里最容易藏 bug 的层之一。

### 10.5 Pacemaker 最小本地状态

每个 validator 的 pacemaker 至少维护：

- `current_height`
- `current_round`
- `round_started_at`
- `proposal_deadline`
- `prepare_deadline`
- `precommit_deadline`
- `commit_deadline`
- `highest_qc`
- `locked_qc`
- `highest_tc`

这些状态不应散落在：

- transport handler
- CLI 层
- 临时测试脚本

而应当有一个明确的共识运行时对象统一维护。

### 10.6 Timeout 长度的工程建议

MVP 中 timeout 不追求最优，而追求行为清楚。

建议：

1. 同一高度内，round timeout 采用递增退避
2. `proposal_timeout <= prepare_timeout <= precommit_timeout <= commit_timeout`
3. 新高度开始时，timeout 重新回到基线值

一个可接受的 MVP 形式是：

```text
base_timeout_ms
round_timeout_ms(h, r) = base_timeout_ms * 2^(min(r-1, cap))
```

这里的 `cap` 用于避免退避无限增长。

### 10.7 收到更高证书时的推进规则

若节点在本轮 timeout 前收到：

- 更高 round 的 `QC`
- 或更高 round 的 `TC`

则 pacemaker 可以直接跳到更高 round，但必须满足：

1. 不得回退到更低 round
2. 不得丢掉本地更高的 `locked_qc`
3. 跳转后必须重置当前 round 的 deadline

这条规则是为了避免节点在旧轮次里空转。

---

## 11. Receipt 与应用层边界

这部分必须严格固定，避免把“已提议”“已预提交”“已最终确认”混在一起。

规则如下：

1. `PREPARE` 后不得发 Receipt
2. `PRECOMMIT` 后不得发 Receipt
3. 只有 `CommitQC` 形成后，才允许：
   - 写盘块状态
   - 更新 sender 最新 confirmed seq
   - 推送或缓存 Receipt

### 11.1 应用链状态和共识状态的提交顺序

为避免“Receipt 发出去了，但块其实没 final”这类严重错误，提交顺序固定为：

1. `CommitQC` 形成
2. 本地把块标记为 final
3. 本地更新：
   - `height`
   - `block_hash`
   - `state_root`
   - `seed_h`
4. 本地更新 sender confirmed seq
5. 本地写入 Receipt 缓存
6. 然后才允许：
   - 主动推送 Receipt
   - 响应 `GetReceipt`

任何实现如果把 5、6 提前到 1 之前，都属于协议错误。

### 11.2 `consensus_extra` 的明确用法

当前仓库已经有 `BlockHeader.consensus_extra`。

MVP 对它的使用态度固定如下：

#### 允许临时放进去的内容

- `epoch_id`
- `validator_set_hash`
- `justify_qc_ref`
- proposer 的最小共识元数据引用

#### 不建议长期放进去的内容

- 完整 `QC`
- 完整 `TC`
- 大量 vote 列表
- 大体积 proposer 证明材料

原因：

- `consensus_extra` 适合过渡，不适合长期承担整套正式共识对象

#### 最稳的 MVP 落法

MVP 推荐：

1. `Proposal` 携带完整共识元数据
2. `BlockHeader.consensus_extra` 只保存：
   - `epoch_id`
   - `validator_set_hash`
   - `justify_qc_hash`
3. 完整 `QC / TC` 单独落在共识状态存储里

这样既能利用当前已有区块头结构，又不会把所有共识对象都硬塞进区块头。

这条规则是后续应用层、钱包层和 release 判断的硬边界。

---

## 12. Mempool 规则

MVP 中共识相关 mempool 规则固定为：

1. 每个 sender 最多一个待执行 Bundle
2. 每轮提议只从该轮 `snapshot_cutoff` 前的 mempool 快照取包
3. `snapshot_cutoff` 后到达的 Bundle 自动进入下一轮候选
4. 区块最终确认后：
   - winner 删除已确认 Bundle
   - non-winner 在验块并 final 后，也必须删除本地对应 Bundle

第 4 条不是可选项，必须和最终确认状态一起推进。

---

## 13. 持久化要求

MVP 中共识节点至少必须持久化：

1. 当前 `height`
2. 当前最终确认块哈希
3. 当前最终确认 `state_root`
4. 当前 `seed_h`
5. 当前 epoch validator set
6. `highest_qc`
7. `locked_qc`
8. 最近若干轮 `QC / TC`
9. 最近 `R` 块 Receipt 缓存

如果这些状态不落盘，节点重启后很容易做出不安全行为。

此外还应至少持久化：

10. 当前 `epoch_id`
11. 当前 `validator_set_hash`
12. 当前 validator set 的只读视图

建议再加：

13. 最近已见 proposal 摘要
14. 最近已发送 vote 记录
15. 最近已形成的 `PrepareQC / PreCommitQC / CommitQC / TC`

否则节点重启后很容易重复投票或错误地重复组装证书。

### 13.1 建议的最小持久化表

为了减少后续实现各写一套，建议最少拆成下面这些逻辑表：

1. `consensus_metadata`
   - 当前 `height`
   - 当前 final `block_hash`
   - 当前 final `state_root`
   - 当前 `seed`
   - 当前 `epoch_id`
   - 当前 `validator_set_hash`
2. `validator_set_snapshot`
   - `epoch_id`
   - `validator_id`
   - `consensus_vote_pubkey`
   - `vrf_pubkey`
   - `weight`
3. `qc_store`
   - `phase`
   - `height`
   - `round`
   - `block_hash`
   - `qc_hash`
   - signer 集
4. `tc_store`
   - `height`
   - `round`
   - `tc_hash`
   - signer 集
   - `highest_qc_hash`
5. `proposal_store`
   - `height`
   - `round`
   - `block_hash`
   - `proposer_id`
   - `proposal_hash`
6. `vote_log`
   - `height`
   - `round`
   - `phase`
   - `voter_id`
   - `block_hash`
   - 已发送 / 已接收标记

后续如果实现层不完全照这个表名走，至少语义上不能缺这些槽位。

### 13.2 共识对象的规范编码草案

为避免共识对象在不同模块里各自序列化，MVP 必须继续沿用 V2 现有的：

- `canonical_encode(...)`
- 域分离哈希

推荐为共识对象新增下面这些确定性摘要：

```text
proposal_hash = H(
  "EZCHAIN_V2_PROPOSAL_OBJ"
  || canonical_encode(
       chain_id,
       epoch_id,
       validator_set_hash,
       height,
       round,
       proposer_id,
       vrf_output,
       block_hash,
       justify_qc_hash
     )
)
```

```text
vote_hash = H(
  "EZCHAIN_V2_VOTE_OBJ"
  || canonical_encode(
       chain_id,
       epoch_id,
       validator_set_hash,
       phase,
       height,
       round,
       voter_id,
       block_hash,
       justify_qc_hash
     )
)
```

```text
timeout_vote_hash = H(
  "EZCHAIN_V2_TIMEOUT_VOTE_OBJ"
  || canonical_encode(
       chain_id,
       epoch_id,
       validator_set_hash,
       height,
       round,
       voter_id,
       highest_qc_hash
     )
)
```

```text
qc_hash = H(
  "EZCHAIN_V2_QC_OBJ"
  || canonical_encode(
       phase,
       height,
       round,
       block_hash,
       signer_ids
     )
)
```

```text
tc_hash = H(
  "EZCHAIN_V2_TC_OBJ"
  || canonical_encode(
       height,
       round,
       highest_qc_hash,
       signer_ids
     )
)
```

约束：

1. `signer_ids` 在进入 `QC / TC` 哈希前必须先排序
2. `signatures` 自身不进入 `qc_hash / tc_hash`
3. `QC / TC` 的身份由“被哪些人签了什么对象”决定，而不是由签名字节顺序决定

### 13.3 Proposal / Vote / QC 的存储对象和传输对象分离

为了减少实现时的混乱，MVP 先固定一个规则：

- **传输对象**
  - 为了网络交互完整，允许带：
    - 证明
    - 完整 `QC`
    - 必要引用
- **存储对象**
  - 为了本地持久化紧凑，优先存：
    - `*_hash`
    - 必要字段
    - 原始签名

也就是说，后续实现里不要把：

- 网络传输 JSON
- 本地数据库记录
- 内存核心对象

混成同一个大 dataclass。

---

## 14. 实现模块边界

为了避免共识代码写散，MVP 先固定推荐文件归属。

### 14.1 建议的 `EZ_V2` 共识模块切分

推荐新增目录：

```text
EZ_V2/consensus/
```

建议至少拆成这些文件：

1. `types.py`
   - `Proposal`
   - `Vote`
   - `QC`
   - `TC`
   - `ConsensusValidator`
   - `ConsensusGenesisConfig`
2. `validator_set.py`
   - validator set 装载
   - `validator_set_hash` 计算
   - epoch 视图
3. `sortition.py`
   - VRF proposer 选择
   - proposer_threshold 逻辑
4. `core.py`
   - safety rule
   - proposal 校验
   - vote 决策
   - commit 判定
5. `pacemaker.py`
   - round timeout
   - TC 处理
   - round 推进
6. `qc.py`
   - QC / TC 组装
   - 阈值检查
   - 签名校验
7. `store.py`
   - 共识状态落盘
   - metadata / qc / tc / vote_log
8. `runner.py`
   - 单个 consensus node 的主循环编排

### 14.2 与现有文件的关系

后续归属建议固定为：

- [network_host.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZ_V2/network_host.py)
  - 继续负责：
    - 网络消息宿主
    - transport 适配
    - account / consensus host 外壳
  - 不应继续塞入越来越多的共识状态机判断

- [chain.py](/Users/lx/Documents/New%20project/EZchain-under-reconstruction-/EZ_V2/chain.py)
  - 继续负责：
    - `DiffPackage`
    - `state_root`
    - `diff_root`
    - 区块应用与验证
  - 不负责：
    - round timeout
    - QC / TC 状态机
    - proposer 轮换

- `EZ_App/`
  - 不负责共识规则本身
  - 只负责：
    - 启动模式
    - 配置
    - CLI / service

### 14.3 一个明确禁令

后续实现时，下面这种写法不允许出现：

- 在 `network_host.py` 里同时维护：
  - VRF 选举
  - QC 组装
  - timeout 退避
  - safety rule
  - 应用层 service 输出

这样会很快失控。

必须坚持：

- 共识规则进 `EZ_V2/consensus/`
- transport 宿主留在 `network_host.py`
- App 编排留在 `EZ_App/`

---

## 15. MVP 明确不做的内容

为了保证第一版可实现、可审查，下面这些内容明确不在 MVP：

1. 随机投票委员会
2. stake 权重
3. 动态 validator 轮换
4. 完整 Algorand BA* recovery mode
5. threshold signature / aggregate signature
6. pipelined chained HotStuff
7. slashing / stake economics

这些都可以是下一阶段，但不能和第一版安全边界混在一起。

---

## 16. 测试要求

共识层开始实现后，最少必须覆盖：

1. `4` 共识节点正常确认单块
2. proposer 超时后进入下一轮
3. 同一高度多个 proposal，只接受最优 VRF proposal
4. 非法 VRF proof 被拒收
5. 非法 `DiffPackage` 被拒收
6. `PrepareQC / PreCommitQC / CommitQC` 阈值正确
7. 节点重启后可恢复 `highest_qc / locked_qc / seed`
8. 只有 final 后才产生 Receipt
9. 同高度双提交被拒绝
10. 网络延迟下不会出现同高度双 final

建议额外覆盖：

11. 节点重启后不会对同一 `(height, round, phase)` 重复投不同块
12. `validator_set_hash` 不一致的 proposal / vote 会被拒收
13. `epoch_id` 不一致的 proposal / vote 会被拒收
14. `consensus_extra` 中的 `justify_qc_hash` 与 proposal 内实际 `justify_qc` 不一致时会被拒收

### 16.1 单元测试

这部分只测纯规则，不拉起多节点。

最少应覆盖：

1. `validator_set_hash` 计算稳定
2. VRF proposer 排序规则稳定
3. `proposal_hash / vote_hash / qc_hash / tc_hash` 稳定
4. safety rule 对合法 proposal 放行
5. safety rule 对冲突 proposal 拒绝
6. QC / TC 阈值计算正确
7. pacemaker timeout 退避正确

### 16.2 多节点仿真测试

这部分用静态网络或 TCP 仿真，至少覆盖：

1. `4` 共识节点单块 final
2. proposer 超时进入下一轮
3. 更高 QC 触发跳轮
4. 节点重启后恢复 `highest_qc / locked_qc`
5. final 后才发 Receipt
6. non-winner final 后清本地 mempool

### 16.3 发布前门口

这部分不是普通回归，而是发布判断项。

建议未来新增：

- `consensus_gate`

其最小要求应包含：

1. `4` 共识节点基本 final 流程通过
2. proposer 超时恢复通过
3. 非法 proposal / 非法 vote / 非法 QC 拒收通过
4. 重启恢复通过
5. final 后 Receipt 才产生的约束通过

在这条门口没有通过前，不应把“正式共识层已接入”写进 readiness。

---

## 17. 与 Algorand 的关系

本方案借鉴 Algorand 的核心思想：

- VRF 自选 proposer
- 随机性驱动的 leader 产生
- 对边缘设备和消费级硬件友好的方向

但它不是“原样照搬 Algorand BA*”。

本方案与 Algorand 的差别是：

1. MVP 中只对 proposer 用 VRF，不对 voting committee 用 VRF。
2. 确认层采用 HotStuff 风格三阶段 BFT，而不是 Algorand 的完整 soft-vote / certify-vote / recovery 流程。
3. validator set 在 MVP 中是许可型、等权重，而不是 Pure PoS。

这是刻意选择，不是遗漏。

原因是：

- 先把共识安全边界做稳
- 再谈更大规模的委员会化扩展

### 16.1 与 `relab/hotstuff` 的关系

本方案在实现结构上，会参考 `relab/hotstuff` 的这些经验：

1. 把 consensus core、crypto/QC、synchronizer、leader 选择拆开
2. 把“是否投票”“何时 commit”收成清晰规则层
3. 把 pacemaker 视为独立模块，而不是附属逻辑

但 EZchain 不会原样照搬它的默认 leader rotation，因为：

- `relab/hotstuff` 主要提供固定 leader / round-robin 等可替换模块
- EZchain 这里明确要换成 VRF proposer sortition

---

## 18. 参考资料

本设计在思想和边界上主要参考：

1. Algorand Developer Portal: Consensus Overview
   - https://developer.algorand.org/docs/get-details/algorand_consensus/
2. Algorand Specifications: General Concepts
   - https://specs.algorand.co/abft/non-normative/abft-nn-general-concepts
3. Algorand official implementation repository
   - https://github.com/algorand/go-algorand
4. relab/hotstuff official repository
   - https://github.com/relab/hotstuff

同时，本文件必须与以下 EZchain 文档一起阅读：

- `EZchain-V2-protocol-draft.md`
- `EZchain-V2-small-scale-simulation.md`
- `EZchain-V2-implementation-roadmap.md`
- `EZchain-V2-network-and-transport-plan.md`

---

## 19. 最终定稿

EZchain V2 共识 MVP 的正式默认路线为：

- **固定 validator set**
- **VRF 随机选 proposer**
- **HotStuff 风格三阶段 BFT**
- **CommitQC 后 final**
- **final 后才允许发 Receipt**

后续实现、测试、readiness 和对外口径，都必须以这条路线为准。
