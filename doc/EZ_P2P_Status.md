# EZchain P2P 模块当前状态说明（MVP）

本文件基于 `p2p_requirements.md` 的最新修改，记录当前最基础、最简单的 P2P MVP 实现现状、快速测试方法与下一步计划。

## 概述
- 目标：独立、可插拔的最小 P2P 通讯模块，支持账户与共识节点的基本点对点交互。
- 状态：已完成最小可运行闭环（HELLO/WELCOME 握手、PING/PONG 保活、ACCTXN_SUBMIT 已对接交易池入库）。
- 位置：`modules/ez_p2p/`

## 已实现功能
- 传输层：
  - 默认：`asyncio` TCP 长连接，4 字节长度前缀分帧。
  - 可选：`libp2p` 传输（基于 go-libp2p-daemon + p2pclient，复用成熟网络栈，默认关闭）。
- 编解码：统一 JSON envelope（version/network/type/msg_id/timestamp/payload）。
- 路由：注册式处理器，内置 `HELLO`、`WELCOME`、`PING`、`PONG` 处理。
- Peer 管理：内存级 `PeerManager` 保存节点角色与地址。
- 基础 API（Router）：
  - `broadcastToConsensus(msg)`
  - `sendToAccount(account_addr, msg)`
  - `sendAccountToConsensus(msg)`
  - `sendConsensusToAccount(account_addr, msg)`
- Demo：
  - `modules/ez_p2p/demo/p2p_gateway.py`（共识/矿工网关，对接 `TXPool` 入库 `ACCTXN_SUBMIT`）。
  - `modules/ez_p2p/demo/account_node.py`（账户节点，发送 `HELLO`、`PING`、`ACCTXN_SUBMIT`）。
- 适配器：新增 `txpool_adapter`，桥接 `EZ_Tx_Pool.TXPool.add_submit_tx_info(...)`。
- 日志：结构化 JSON 输出；修复了握手时“拨回临时端口”的问题，现原路复用入站连接回复，避免 `dial_failed` 噪声。

## 目录结构（节选）
```
modules/ez_p2p/
  __init__.py
  config.py              # P2PConfig
  logger.py              # JSON 日志
  peer_manager.py        # PeerInfo / PeerManager
  router.py              # Router + 内置处理器
  codec/
    __init__.py
    json_codec.py        # 消息 envelope 编解码
  transport/
    __init__.py
    tcp.py               # asyncio TCP + length-prefix
  demo/
    p2p_gateway.py       # 共识/矿工网关 demo
    account_node.py      # 账户节点 demo
    config/
      gateway.json
      account.json
```

## 环境要求
- Python 3.10+
- 无三方依赖（标准库）

## 快速测试
1) 启动网关（终端1）：
   - `EZ_P2P_CONFIG=modules/ez_p2p/demo/config/gateway.json python modules/ez_p2p/demo/p2p_gateway.py`
2) 启动账户（终端2）：
   - `EZ_P2P_CONFIG=modules/ez_p2p/demo/config/account.json python modules/ez_p2p/demo/account_node.py`

### 预期日志关键点
- 网关：`server_listen` → `hello_recv` → `ping_recv` → `acctxn_submit_recv`（含 `{"ok": true, "result": "SubmitTxInfo added successfully"}`）
- 账户：`server_listen` → `welcome_recv` → `pong_recv`

注意：首次运行会在仓库根目录创建 `tx_pool_demo.db`（SQLite），作为交易池示例数据库。

若仍看到 `dial_failed`，请确认使用的是本仓库当前版本；新版本已在同一连接上回复 WELCOME/PONG，避免回拨到临时端口。

### 使用 libp2p（可选，高阶）
- 前置：
  - 安装并运行 go-libp2p-daemon（p2pd），示例：`p2pd -listen /ip4/0.0.0.0/tcp/4001 -daemon-sock /tmp/p2pd.sock`
  - 安装 Python 包：`pip install p2pclient`
- 配置示例（account）：
  ```json
  {
    "node_role": "account",
    "transport": "libp2p",
    "libp2p_control_path": "/tmp/p2pd.sock",
    "libp2p_protocol": "/ez/1.0.0",
    "peer_seeds": ["/ip4/127.0.0.1/tcp/4001/p2p/<gateway_peer_id>"]
  }
  ```
- 说明：
  - Router 使用 `Libp2pDaemonTransport` 注册协议 `/ez/1.0.0`，以 libp2p stream 处理点对点消息；消息格式仍为统一 JSON envelope。
  - 广播在 M3 阶段将映射为 gossipsub 主题（如 `ez/consensus/blocks`）。

## 已知限制（MVP）
- 已接入 `TXPool`，但尚未接入 `Blockchain`、`VPB` 适配器。
- 未实现 `BLOCK_BROADCAST`、`VW_TRANSFER`、`MTPROOF_REQ/RESP`、`CHAIN_STATE_REQ/RESP`、`PEX` 等业务消息与流程。
- 无去重、限流、健康重连等稳健性策略（文档已有规划）。
- 已支持消息信封身份字段（`sender_id/public_key/signature`）与签名验真；
  可通过配置 `enforce_identity_verification=true` 强制校验（握手与关键交易消息）。

## 下一步计划（按优先级）
1) 区块广播路径（M3）
   - `BLOCK_BROADCAST` 消息与 `blockchain_adapter`；支持仅头信息的轻量广播。
   - 账户节点可订阅或直连获取广播。
2) VW 与证明（M4）
   - `VW_TRANSFER` 点对点；`MTPROOF_REQ/RESP` 链路与 `MerkleTreeProof` 字典化传输。
   - `vpb_adapter` 与 `VerVW` 回调对接。
3) 发现与链状态（增强）
   - `PEX`（最小发现）与 `CHAIN_STATE_REQ/RESP`（Tip/Headers/Bloom 查询）。
4) 稳健性与可观测性（M5）
   - 去重缓存、消息大小上限、限流与重试、断线重连；完善指标与日志字段。
5) 账户端回执（可选）
   - `ACCTXN_RESULT` 回执消息（成功/失败、错误原因），改善交互体验。

## 故障排查
- 端口占用：修改 `demo/config/*.json` 中的 `listen_port`，确保不冲突。
- 连接失败：确认 `peer_seeds` 指向的 `host:port` 正确且网关已启动。
- 无日志输出：确保通过 `EZ_P2P_CONFIG` 指定了正确的 JSON 配置文件路径。

## 参考
- 需求文档：`p2p_requirements.md`
- 主要相关实现：
  - 交易池：`EZ_Tx_Pool/TXPool.py`
  - 区块与主链：`EZ_Main_Chain/Block.py`、`EZ_Main_Chain/Blockchain.py`
  - Merkle 证明：`EZ_Units/MerkleProof.py`
  - VPB：`EZ_VPB/*`
