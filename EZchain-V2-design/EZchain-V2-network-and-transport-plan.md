# EZchain V2 网络与传输层规划

## 1. 文档目的

本文档定义 V2 后续落地时的网络层原则，解决三个问题：

1. V2 节点之间如何通信；
2. 传输层先做什么、后做什么；
3. 在未决定 DPoS / BFT 之前，如何避免把共识算法和网络层绑死。

本文档是 `EZchain-V2-implementation-roadmap.md` 的补充，不替代协议草案。

## 2. 当前现实

当前仓库的 V2 已经具备：

- 本地 `runtime`
- 本地 `consensus store`
- 钱包/receipt/transfer 闭环
- 基于静态 peers 的最小网络宿主骨架

当前仓库的 V2 仍然缺少：

- 真正运行在 socket/libp2p 之上的 V2 节点传输层
- 节点发现
- 区块/receipt/状态补同步
- 正式测试网级别的多节点运行闭环

因此，后续网络层开发目标不是“再造一个 demo P2P”，而是为 V2 节点系统提供稳定的传输底座。

## 3. 总体原则

### 3.1 先固定网络消息面，再替换传输实现

V2 先固定一层与共识算法无关的消息：

- `bundle_submit`
- `bundle_ack`
- `bundle_reject`
- `block_announce`
- `block_fetch_req/resp`
- `receipt_deliver`
- `receipt_req/resp`
- `transfer_package_deliver`
- `chain_state_req/resp`
- `checkpoint_req/resp`
- `peer_info`
- `peer_health`

上层节点宿主与同步逻辑只能依赖这层消息，不得依赖某个特定传输库。

### 3.2 先 TCP，后 libp2p

第一阶段默认传输层采用 TCP。

原因：

- 更容易本地调试；
- CI 更稳定；
- 依赖更少；
- 适合先把 V2 节点与同步逻辑跑通。

第二阶段再引入 libp2p 作为可插拔 backend，而不是一开始就作为唯一主路径。

### 3.3 共识算法与网络层解耦

无论后续采用 DPoS 还是 BFT，网络层都只提供：

- 提议消息传输
- 区块传输
- receipt / state / transfer 同步
- peer 管理

真正的共识选择只通过共识适配器接入：

- `propose_block`
- `validate_proposal`
- `commit_block`
- `finality_event`

## 4. 实施顺序

### 阶段 A：Transport 抽象

新增统一接口：

- `NetworkTransport`
- `set_handler`
- `start`
- `stop`
- `send`

并提供：

- `TCPNetworkTransport`
- 内存静态网络仅保留给测试和本地 smoke

### 阶段 B：静态拓扑 TCP 网络

先支持：

- 静态 seed
- 明确的账户节点 / 共识节点角色
- 点对点直连
- request/response 风格的区块、receipt、状态请求

这一阶段不做复杂发现。

### 阶段 C：同步与恢复

补齐：

- `block_fetch`
- `receipt_sync`
- `chain_state_sync`
- 新节点 bootstrap
- 节点重启追平

### 阶段 D：最小发现

只做最小 peer exchange，不做复杂自治发现。

### 阶段 E：libp2p backend

在 TCP 路径稳定后，引入 libp2p backend：

- 保持同一组 V2 网络消息
- 保持同一组节点宿主逻辑
- 只替换 transport adapter

## 5. 当前默认决策

当前默认结论固定如下：

1. V2 主网络层近期采用 TCP；
2. libp2p 是中期增强选项，不是当前主路径；
3. 静态 peers 是第一阶段默认拓扑；
4. 节点发现不是当前最优先事项；
5. 不在当前阶段绑定 DPoS 或 BFT。

## 6. 验收标准

当以下条件满足时，可认为 V2 网络层第一阶段完成：

1. 账户节点可通过真实 TCP transport 向共识节点提交 `bundle`；
2. 共识节点可返回 `receipt`；
3. transfer package 可跨节点送达；
4. 节点可请求并获得链状态；
5. 相关 smoke 与自动化测试稳定通过；
6. 上层节点逻辑不依赖具体 transport 实现。
