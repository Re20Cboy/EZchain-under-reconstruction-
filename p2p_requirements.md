# EZchain P2P 通讯模块需求文档（外包交付版）

## 0. 文档目的
本需求定义一个“独立落地、可插拔接入”的 P2P 通讯模块，用于实现 EZchain 实现版所需的两类通讯：  
- 共识网络广播：共识节点之间广播 `<Block, SigInfos>`。  
- 支持共识节点和账户节点的点对点通讯和信息传输：账户节点之间传输 `<v, w>`（VW pair），并支持账户向矿工/共识节点请求与主链相关的必要信息（不局限于 Merkle 证明，还可能包括区块头、Bloom 命中查询、区块高度/Tip、部分链数据等）。

本需求强调隔离：模块必须放入单独文件夹，默认不影响项目现有代码与构建流程。

---

## 1. 范围与不做事项
### 1.1 范围
- 实现 Peer 管理、连接建立、消息编解码、消息路由与处理器注册机制。
- 支持 3 条关键流程的网络动作：
  1) 账户提交 `AccTxn` 到交易池入口（或模拟入口）。  
  2) 共识节点广播 `<Block, SigInfos>` 到共识网络。  
  3) 账户节点点对点发送 `<v, w>` 给收款方；收款方触发 `VerVW`（由上层提供或桩实现）。

### 1.2 不做事项
- 不实现论文的共识算法、PoW、区块链账本、VWDB、VerVW、VerPool、BuildMTree 等业务逻辑本体（允许提供接口与桩）。
- 不改造项目现有网络栈（除非明确允许通过“可选适配器”接入）。
- 不要求实现跨 NAT 打洞、DHT、复杂发现协议。为保障开放网络中节点加入/退出的可用性，必须提供“最小可用的发现与生命周期管理”：
  - 静态种子与引导节点（配置项 `peer_seeds` 支持域名/IP:port）。
  - 同步期的 PeerExchange（PEX）消息，支持从已连接对等体获取更多可用节点。
  - 节点生命周期状态机与握手（参见“5.4 节点生命周期”），以保障加入、同步、活跃、退出的完整流程。

---

## 2. 隔离与目录要求（硬性）
### 2.1 目录隔离
- 新模块必须放在项目根目录下的独立文件夹，例如：
  - `modules/ez_p2p/`
- 禁止修改现有业务目录文件；禁止引入会改变现有编译/依赖解析的全局配置。
- 若需要接入现有工程，只允许新增一个“可选入口/适配器文件”，并通过开关控制：
  - 例如环境变量 `EZ_P2P_ENABLE=1`
  - 默认关闭，确保不影响现有构建与运行。

### 2.2 独立构建与独立测试
- 模块必须自带：
  - 自己的单元测试目录
  - 自己的 demo/模拟运行入口（可执行或脚本）
- 模块在“未被主工程引用”时，应能独立编译/运行 demo。

---

## 3. 术语与节点角色（统一口径，按仓库实现命名）
- Consensus Node：共识/矿工节点，运行共识广播通道。相关实现：`EZ_Main_Chain.Block`、`EZ_Main_Chain.Blockchain`。
- Account Node：账户/用户节点，运行点对点通道，并在交易期内保持在线。相关实现：`EZ_VPB.values.Value`、`EZ_VPB.proofs/*`、`EZ_VPB.block_index/*`。
- Txn：交易本体，结构 `(Sender, Recipient, Values, Time, Sig)`。相关实现：`EZ_Transaction.SingleTransaction.Transaction`。
- AccTxn / SubmitTxInfo：账户交易提交摘要（用于交易池），对齐实现类 `EZ_Transaction.SubmitTxInfo.SubmitTxInfo`。
- MultiTransactions：打包的多笔交易集合，`EZ_Transaction.MultiTransactions.MultiTransactions`。
- TxPool：交易池实现，`EZ_Tx_Pool.TXPool.TxPool`。
- SigInfos：签名集合（若使用，随区块广播，不要求链上永久存储）。
- VW pair：`<v_ij, w_ij>`，由发送方账户点对点交付给接收方账户；`v` 对齐 `EZ_VPB.values.Value` 的字典化输出，`w` 对齐 proofs + block index 的字典化输出。
- MTree Proof / MerkleTreeProof：Merkle 证明，对齐实现类 `EZ_Units.MerkleProof.MerkleTreeProof`。

---

## 4. 总体架构与模块边界
### 4.1 分层
- Connection Layer：连接建立、断线重连、心跳保活、邻居集合管理。
- Message Layer：消息类型定义、序列化/反序列化、签名与基本校验钩子。
- Routing Layer：广播与点对点发送语义；收包分发到 handler。
- Adapter Layer（可选）：对接主工程的日志、配置、线程模型与事件循环；对接 `TXPool`、`Blockchain`、`VPB/Proofs`。

### 4.2 核心组件
1) `PeerManager`
- 维护邻居集合 `neighbors`，支持“随机建连”与“邻居上限”。
- 默认实现邻居上限 `MAX_NEIGHBORS = 30`（可配置）。
- 提供 `addPeer/removePeer/listPeers/selectPeers()`。

2) `Transport`
- 提供基础收发：`listen/start`, `dial/connect_seed`, `send(addr, bytes)`, `send_via_context(ctx, bytes)`。
- 首选集成成熟网络栈：libp2p（推荐方案）
  - 采用 go-libp2p-daemon（p2pd）+ Python `p2pclient` 绑定，应用协议名 `/ez/1.0.0`；
  - 点对点使用 libp2p streams；区块广播推荐 gossipsub 主题（如 `ez/consensus/blocks`，在 M3 实现）。
- 默认回退：`asyncio` TCP 长连接（长度前缀分帧），零依赖，便于本地与 CI 演示。
- 必须支持超时与重试策略（配置化）。

3) `Codec`
- 负责消息编码/解码：
  - 使用 length-prefix framing；payload 采用 JSON 文本（跨语言、易调试、零额外依赖）。
  - 二进制字段（签名、哈希、proof 等）采用 hex 或 base64 表示；禁止在网络层使用 pickle。

4) `Router`
- 提供三类发送 API：
  - `broadcastToConsensus(msg)`：共识广播
  - `sendToAccount(accountId, msg)`：账户点对点
  - `sendAccountToConsensus(msg)`：账户侧发往共识/矿工入口（提交/查询）
  - `sendConsensusToAccount(accountId, msg)`：共识/矿工侧主动点对点下发（如证明、同步提示）
  - `sendToPoolGateway(msg)`：提交到交易池入口（可为模拟服务）
- 提供 `registerHandler(msgType, handler)` 与默认拒绝策略。

5) `Handlers`
- `onBlockBroadcast(Block, SigInfos)`
- `onAccTxnSubmit(AccTxn)`
- `onVWTransfer(v, w)`
- `onMtProofRequest(hash)` / `onMtProofResponse(proof)`（可选但建议实现通道）
- `onChainStateRequest(query)` / `onChainStateResponse(partial)`（账户与共识之间的主链部分信息查询）

### 4.3 适配器（强烈建议）
- txpool_adapter：将 `onAccTxnSubmit` 映射到 `EZ_Tx_Pool.TXPool.add_submit_tx_info(...)`
- blockchain_adapter：将 `onBlockBroadcast` 映射到 `EZ_Main_Chain.Blockchain.add_block(...)`
- vpb_adapter：将 `onVWTransfer` 映射到 `EZ_VPB`（或 `AccountProofManager`）验证并入库（`VerVW` 回调由上层注入）

---

## 5. 网络拓扑与连接策略
### 5.1 两张网络
- 共识网络：Consensus Node 之间相互连接，使用广播传播块与 SigInfos。
- 账户网络：Account Node 与 Account Node/矿工之间可建立会话，用于点对点 `<v,w>` 与 `MtProof` 请求。
（libp2p 模式：共识广播推荐 gossipsub；点对点使用 streams，具备内置加密与多路复用。）

### 5.2 邻居管理（必须）
- 节点启动后，随机选择 peer 建连，直到达到 `MAX_NEIGHBORS`。
- 节点周期性检查连接健康度，剔除失活连接，再补足邻居。
- 节点支持静态 peer 列表（配置文件）与运行时注入（API）。

### 5.3 在线状态要求（必须支持）
- Account Node 允许上下线，但需支持在“交易执行窗口”保持在线：
  - 模块需提供 session 保活、发送重试、超时回调，避免调用方阻塞。

### 5.4 节点生命周期（必须具备最小流程）
- 共识节点生命周期（参考 BTC/ETH 简化态机）：
  - `INIT` 启动加载配置与密钥 -> `DISCOVERING` 通过 `peer_seeds` 与 PEX 获取候选 ->
  - `CONNECTING` 与若干 peer 建连并握手（版本、网络ID、角色、最高高度）->
  - `SYNCING` 同步区块头/高度与必要元信息（允许只交换索引/摘要）->
  - `ACTIVE` 参与广播与转发；维持 `max_neighbors`；健康检查/重连 ->
  - `LEAVING` 优雅下线（告知邻居、释放资源）-> `OFFLINE`。
- 账户节点生命周期（点对点特化）：
  - `INIT` -> `CONNECTING`（按需连接矿工/目标账户）-> `SUBSCRIBED`（可选：订阅广播转发器或矿工通知）->
  - `ACTIVE`（VW 传输、MtProof/链状态查询）-> `IDLE`/`OFFLINE`（无会话时可断链）。
- 最小握手与身份：
  - `HELLO`/`WELCOME` 消息交换角色、协议版本、网络ID、最高区块高度、节点ID（公钥或指纹）。
  - 连接存活期间周期性 `PING/PONG`。
  - 基础黑名单/限流与失败回退策略。

---

## 6. 消息定义（必须实现）
### 6.1 通用消息封装
每条网络消息使用统一 envelope：
- `version`
- `network`（consensus/account）
- `type`
- `msg_id`
- `timestamp`
- `payload`（bytes）
- `sig`（可选，若上层要求）

### 6.2 业务消息类型
为对齐现有代码（`EZ_Transaction.SubmitTxInfo.SubmitTxInfo`、`EZ_Main_Chain.Block`、`EZ_VPB.values.Value`、`EZ_Units.MerkleProof.MerkleTreeProof`），采用 JSON 载荷并按如下字段定义：

1) `TXN`（可选，用于调试/扩展）
- 字段：`sender, recipient, value, timestamp, signature`
- 校验：验签钩子（由上层注入）

2) `ACCTXN_SUBMIT`（对齐 SubmitTxInfo）
- 字段：
  - `multi_transactions_hash`
  - `submit_timestamp`
  - `version`
  - `submitter_address`
  - `signature`（hex 或 base64）
  - `public_key`（hex 或 base64）
- 路由：Account Node -> Pool Gateway（或矿工入口）
- 处理：适配到 `TXPool.add_submit_tx_info(...)`（可选附带 `MultiTransactions`，否则做结构/签名格式校验）

3) `BLOCK_BROADCAST`
- 字段：
  - `block`: `{index, nonce, bloom(序列化JSON), m_tree_root, time(ISO), miner, pre_hash, version, sig}`
  - `siginfos`（可选，默认可空，占位）
- 路由：Consensus Node -> Consensus Node peers（广播）。libp2p 模式建议采用 gossipsub 主题（如 `ez/consensus/blocks`）；TCP 模式由 Router 扇出到选定邻居。
- 处理：适配到 `Blockchain.add_block(...)`；`siginfos` 可由上层校验桩消费

4) `VW_TRANSFER`
- 字段：
  - `v`: `Value.to_dict_for_signing()` 输出（去状态）
  - `w`: `{proofs: Proofs/ProofUnit(s) 的 to_dict, block_index_list: to_dict}`
- 路由：Account Node(i) -> Account Node(j)（点对点）
- 处理：回调 `VerVW(v, w)`（上层提供），通过后由 `vpb_adapter` 写入 VPB 系统

5) `MTPROOF_REQ / MTPROOF_RESP`
- 请求字段（REQ）：`{submitter_address, multi_transactions_hash}` 或 AccTxn 唯一标识
- 响应字段（RESP）：`{proof: MerkleTreeProof.to_dict()}`
- 路由：Account Node <-> Miner（点对点或走共识网络服务端口）
- 处理：仅传输与回调；不解释 proof 结构

6) `CHAIN_STATE_REQ / CHAIN_STATE_RESP`（主链部分信息查询）
- 请求字段：`{type: headers|tip|bloom_query, from_index?, count?, query_item?}`
- 响应字段：
  - `headers`: `[{index, pre_hash, m_tree_root, time, miner, version, sig}]`
  - `tip`: `{latest_index, latest_hash}`
  - `bloom_query`: `{block_index, hit: bool}` 或更丰富结果
- 路由：Account Node <-> Consensus/Miner
- 处理：由 `blockchain_adapter` 提供只读查询实现（不涉及账本写操作）

7) `PEX`（Peer Exchange，用于最小发现）
- 字段：`{peers: ["host:port", ...]}`
- 路由：任意已连接节点之间按限速交换，避免风暴
- 处理：`PeerManager.addPeer(...)` 按策略接纳

8) `HELLO / WELCOME`（握手）与 `PING / PONG`（保活）
- `HELLO/WELCOME` 字段：`{node_id, role(consensus|account|gateway), protocol_version, network_id, latest_index}`
- `PING/PONG` 字段：`{ts, nonce}`
- 处理：用于建立与维持连接，不进入业务处理统计

---

## 7. 关键流程与时序（必须跑通 demo）
### 7.1 账户侧流程（最小闭环）
1) 生成若干 `Txn`
2) 打包为 `AccTxn` 并发送 `ACCTXN_SUBMIT`
3) 等待 `BLOCK_BROADCAST`（可由 demo 里的 miner 模拟广播）
4) 触发 `MTPROOF_REQ` 并接收 `MTPROOF_RESP`（可由 miner 模拟）
5) 点对点发送 `VW_TRANSFER` 给收款方
6) 收款方触发 `VerVW` 回调，并打印“验证通过/失败”

### 7.2 共识侧流程（最小闭环）
1) 从 pool gateway 收到 `ACCTXN_SUBMIT`（可存入内存队列）
2) 构造模拟 `Block` 与 `SigInfos`
3) 广播 `BLOCK_BROADCAST` 给所有共识 peers
4) 允许账户节点订阅或直接连接到一个“广播转发器”（demo 方案二选一）

### 7.3 Demo 角色建议
- `p2p_gateway`：共识/矿工侧模拟进程（内含 TXPool 与 Blockchain 适配器）
- `account_node`：账户端进程（内含 VPB 适配器与 VerVW 回调）
- 使用同机不同端口与静态 seed 列表，便于演示与CI

---

## 8. 配置、日志与可观测性（必须）
### 8.1 配置项
- `node_role`: `consensus|account|pool_gateway`
- `listen_addr`
- `peer_seeds`: list
- `max_neighbors`（默认 30）
- `dial_timeout_ms`, `send_timeout_ms`, `retry_count`, `retry_backoff_ms`
- `network_id`（区分测试网/主网）
- `msg_size_limit_bytes`（默认 1–4MB）
- `dedup_window_ms`（默认 5–10 分钟）
 - `transport`: `tcp|libp2p`（默认 `tcp`）
 - `libp2p_control_path`（p2pd 控制通道路径，UNIX/TCP）
 - `libp2p_protocol`（应用协议名，默认 `/ez/1.0.0`）
 - `libp2p_bootstrap`（multiaddrs 列表，用于初始连接/发现）

### 8.2 日志与指标
- 必须输出结构化日志（JSON 或 key-value）：
  - 连接建立/断开、重试、超时
  - 每种消息的收发计数、丢弃原因（未知类型/校验失败/超时）
- 建议输出基础指标（stdout 或 prometheus endpoint 二选一）：
  - peers 数量、广播 fanout 数、消息处理耗时分布
  - 关键 handler 的 p95/p99 耗时

---

## 9. 可靠性与安全约束（必须）
- 必须实现消息大小上限与拒绝策略，防止内存打爆。
- 必须实现 `msg_id` 去重缓存（可配置窗口），降低重复广播影响。
- 必须实现基础签名校验接口，但允许上层不启用。
- 必须对未知消息类型采取默认拒绝，不得崩溃。
- 去重缓存建议基于 TTL LRU；超大 JSON 载荷直接拒绝并记录原因。

---

## 10. 交付物清单（必须）
1) 模块源码（位于独立目录）
2) `README.md`
- 如何构建
- 如何运行 demo（至少包括 account + miner + gateway 的启动步骤）
- 配置说明
3) `requirements.txt`（若使用 WebSocket/Prometheus 等）
4) 适配器参考实现（`txpool_adapter`、`blockchain_adapter`、`vpb_adapter`）

---

## 11. 里程碑与验收标准
- M1（通信骨架）：Transport + Codec(JSON) + Router + 去重 + 大小限制 + 基础日志
- M2（共识/交易对接）：ACCTXN_SUBMIT 打通 TXPool；BLOCK_BROADCAST 打通 Blockchain
- M3（账户闭环）：VW_TRANSFER + MTPROOF 通道 + 最小闭环 demo 跑通
- M4（稳定性）：结构化日志、配置化、基础性能与稳定性测试（含断线重连与限流）

验收：
- 功能达标：demo 能跑通“AccTxn 提交 -> 广播块 -> 请求 proof -> 发送 VW -> VerVW 回调”链路。
- 隔离达标：默认不开启不影响现有测试；模块可独立运行。
- 文档达标：README 覆盖配置、运行与调试；JSON 载荷字段说明完整。

---

## 12. 目录骨架（建议）

根目录下新增 `modules/ez_p2p/`，默认不影响主工程；通过环境变量 `EZ_P2P_ENABLE=1` 控制启用。

```
modules/
  ez_p2p/
    README.md                      # 模块说明、构建与运行 demo 指南
    requirements.txt               # 可选依赖（如 websockets/prometheus-client）
    ez_p2p/
      __init__.py
      config.py                    # 配置加载与校验（node_role/listen_addr/peer_seeds/限流/去重）
      logger.py                    # 结构化日志封装（JSONFormatter）
      peer_manager.py              # 邻居管理、保活、重连、上限控制
      router.py                    # 路由：broadcast/sendToAccount/sendToPoolGateway、handler 注册
      utils/
        __init__.py
        dedup_cache.py             # msg_id 去重（TTL LRU）
        rate_limiter.py            # 简单令牌桶或漏桶（可选）
      transport/
        __init__.py
        tcp.py                     # asyncio TCP 长连接，length-prefix 分帧
        websocket.py               # 备选传输层（可选）
      codec/
        __init__.py
        framing.py                 # 长度前缀分帧编解码
        json_codec.py              # JSON 编解码，二进制字段 hex/base64
      handlers/
        __init__.py
        consensus_handlers.py      # onBlockBroadcast 等共识侧 handler
        account_handlers.py        # onAccTxnSubmit/onVWTransfer/MtProof handlers
      adapters/
        __init__.py
        txpool_adapter.py          # 适配 TXPool.add_submit_tx_info(...)
        blockchain_adapter.py      # 适配 Blockchain.add_block(...)
        vpb_adapter.py             # 适配 VPB/AccountProofManager（VerVW 回调）
      schemas/
        messages.md                # 消息字段说明与示例（可选 JSON Schema）
    demo/
      p2p_gateway.py               # 共识/矿工侧演示进程（含 TXPool/Blockchain 适配）
      account_node.py              # 账户侧演示进程（含 VPB 适配与 VerVW 桩）
      config/
        gateway.json               # 演示用配置样例
        account_a.json
        account_b.json
    tests/
      __init__.py
      test_peer_manager.py
      test_codec.py
      test_router.py
      test_adapters.py
      test_integration_demo.py     # 最小闭环集成测试（可标记为慢速）
```

实现要点：
- Transport/Codec 可替换：默认 `tcp.py + json_codec.py + framing.py`，WebSocket 作为备选。
- 适配层仅在 `EZ_P2P_ENABLE=1` 时加载；默认不改动主工程依赖与启动路径。
- Demo 运行分为 `p2p_gateway` 与 `account_node` 两个进程，使用静态 seed 列表互联。

---

## 13. 渐进式交付与重构流程（每步可运行/可测试）

### 13.1 流程原则
- 小步可合并：每次提交/PR 控制在中小规模，优先最小可用功能（MVP）。
- 功能开关：所有新功能受 `EZ_P2P_ENABLE=1` 控制，默认关闭，确保不影响现有测试与运行。
- 兼容隔离：不修改现有业务代码，对接仅通过 `adapters/`；移除模块目录即可回滚。
- 协议版本化：消息 envelope 增加 `protocol_version`/`schema_version`（向后兼容演进）。
- 可回滚发布：每个里程碑打 tag（如 `p2p-m1`），文档与demo同步更新。

### 13.2 里程碑拆分与验收（增强）
- M0（脚手架可运行）：
  - 交付：目录骨架、`config/logger/codec(json+framing)`、空实现 `PeerManager/Router`、示例 `demo/* --dry-run`。
  - 可运行：`account_node.py --dry-run` 和 `p2p_gateway.py --dry-run` 可启动、打印健康日志并退出0。
  - 可测试：`test_codec.py`、`test_peer_manager.py` 基本单测通过。

- M1（传输+路由最小闭环）：
  - 交付：`transport.tcp` + length-prefix、去重/大小上限、`PING/PONG` 内置消息。
  - 可运行：本机两进程能完成握手与 `PING/PONG` 往返，日志统计收发计数。
  - 可测试：`test_router.py`、`test_integration_demo.py::test_ping_pong` 通过。

- M1.5（libp2p 可选接入）：
  - 交付：`Libp2pDaemonTransport` 接入与配置开关（保持 TCP 默认）。
  - 可运行：连接 p2pd，完成基本 stream 收发与内置握手/保活。
  - 可测试：在本地或 CI 条件具备时，完成功能冒烟（可选）。

- M2（交易提交路径）：
  - 交付：`ACCTXN_SUBMIT` 消息 + `txpool_adapter` 对接（可选附带 `MultiTransactions`）。
  - 可运行：`account_node` 发送提交；`p2p_gateway` 统计入池成功条数并可查询。
  - 可测试：`test_adapters.py::test_txpool_submit` 校验落库/索引更新。

- M3（区块广播路径）：
  - 交付：`BLOCK_BROADCAST` + `blockchain_adapter`；`siginfos` 可为空且向后兼容。
  - 可运行：`p2p_gateway` 构造模拟块广播；对端 `Blockchain.add_block` 成功，主链高度增长。
  - 可测试：集成测试校验最新高度与哈希链完整性。

- M4（VW 点对点与证明）：
  - 交付：`VW_TRANSFER`（v/w 结构对齐 VPB）、`MTPROOF_REQ/RESP` 通道、`vpb_adapter` 与 `VerVW` 桩。
  - 可运行：A->B 发送 VW，B 触发 `VerVW` 并入库；MtProof 请求-响应链路打通。
  - 可测试：验证回调被调用、VPB 写入与基础一致性。

- M5（可观测性与稳健性）：
  - 交付：结构化日志完善、基础指标、限流与重试策略、断线重连脚本化回归。
  - 可运行：压测/异常场景下连接恢复、限流命中可观测。
  - 可测试：稳定性用例（可标记慢测）通过。

### 13.3 CI 门禁与运行方式
- 命令：`pytest -k ez_p2p`（或 `python -m modules.ez_p2p.tests`）在每个里程碑均需通过。
- 冒烟：`python modules/ez_p2p/demo/p2p_gateway.py` 与 `python modules/ez_p2p/demo/account_node.py` 能启动并完成对应里程碑演示用例。
- 覆盖：核心单元（codec/framing/router/adapters）设定基础覆盖线（如 ≥60%），逐里程碑提升。

### 13.4 发布与回滚
- Tag：`p2p-m1`、`p2p-m2`... 对应README与schemas版本更新。
- 回滚：关闭 `EZ_P2P_ENABLE` 或回退到上一个 tag；模块目录可整体移除不影响主工程。
- API 说明（Router/Handlers 的调用方式）

3) Demo 工程或脚本
- 能在单机启动多个进程/多个端口模拟网络
- 能展示 7.1/7.2 的最小闭环日志

4) 单元测试
- Codec round-trip
- Router 分发
- 去重逻辑
- 超时与重试策略（至少覆盖 2 个用例）

---

## 11. 验收标准（Definition of Done）
- 隔离达标：模块放在独立目录，默认不改动主工程代码且不影响构建。
- 功能达标：demo 能跑通“AccTxn 提交 -> 广播块 -> 请求 proof -> 发送 VW -> VerVW 回调”链路。
- 稳定达标：断开 30% 连接后能自动重连并继续收发；消息丢弃有明确日志原因。
- 可用达标：README 可直接指导他人复现 demo；配置可通过文件或环境变量覆盖。

---

## 12. 里程碑建议（供外包排期）
- M1（连接与路由）：PeerManager + Transport + Router + 基础 demo 发包收包
- M2（消息与广播）：Codec + BLOCK_BROADCAST 广播 + 去重 + 日志
- M3（账户点对点）：VW_TRANSFER + MtProof 通道 + 完整最小闭环 demo
- M4（测试与文档）：补齐单测、README、边界条件与验收脚本
