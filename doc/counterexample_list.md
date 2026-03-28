# EZchain-V2 本地联调反例清单

本文档只记录“值得长期回归”的本地联调反例，而不是完整测试报告。
每条反例都尽量回答 3 个问题：

1. 这个输入组合是不是一个真反例？
2. 当前 EZchain-V2 是已经证明安全、已经发现漏洞，还是仍待验证？
3. 对应证据在哪个测试里？

状态约定：

- `已验证安全`：当前代码和测试表明该反例不会导致错误状态迁移
- `已发现并修复`：联调中确实暴露出实现问题，现已补回归
- `待补`：高价值但还没形成稳定回归用例

## 已落地反例

| ID | 反例 | 为什么值得测 | 当前结论 | 证据 |
| --- | --- | --- | --- | --- |
| CE-001 | 已上链 bundle 在 follower 追平若干块后，被原样重放到另一个 consensus 节点 | 检查跨高度、跨节点、跨 mempool 的 stale replay | `已验证安全`：返回 `bundle seq is not currently executable`，不会重新入池或再次打包 | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_cluster_rejects_replayed_committed_bundle_after_follower_catchup` |
| CE-002 | 同一 sender 的冲突 bundle（相同 seq，不同接收人）在原交易上链并追平后，再投递到另一个 consensus 节点 | 检查“跨块后双花重放”是否会在落后/已追平节点重新复活 | `已验证安全`：返回 stale seq 错误，不会重新执行 | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_cluster_rejects_conflicting_same_seq_bundle_after_follower_catchup` |
| CE-003 | 同一 sender 在同一自动出块窗口内，经不同 consensus endpoint 提交“同 seq 但 sidecar 已变”的冲突 bundle | 这是最接近真实“多入口抢占 mempool”的路径，最容易在 forwarding、replacement、sender receipt 对账之间埋雷 | `已发现并修复`：winner 现在拒绝 `bundle_hash` 已变的冲突替换，返回 `sender already has a different pending bundle`，避免 sender 钱包拿旧 pending sidecar 去验新 receipt | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_mvp_window_rejects_conflicting_cross_endpoint_replacement_with_higher_fee`；实现位于 `EZ_V2/chain.py` |
| CE-004 | 首选 consensus peer 已宕机，但次选 peer 正常 | 检查 account 侧 peer fallback 是否只对抛异常生效，还是也能识别被包装成错误响应的连接失败 | `已发现并修复`：现在会继续尝试下一 peer，成功提交不再被 down peer 污染成失败 | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_cluster_falls_back_when_selected_winner_is_down`；实现位于 `EZ_V2/network_host.py`、`EZ_V2/transport_peer.py` |
| CE-005 | forged / tampered bundle signature | 签名校验是共识入口最高优先级防线之一 | `已验证安全`：非法签名会被拒绝 | `EZ_Test/EZ_V2_New_Test/test_v2_consensus_message_validation.py::test_invalid_bundle_signature_rejected` |
| CE-006 | sender 直接提交跳号 seq（例如 confirmed_seq + 2） | 检查 stale / future bundle 是否能绕过执行序约束 | `已验证安全`：跳号先拒绝，合法 seq 仍可继续执行 | `EZ_Test/EZ_V2_New_Test/test_v2_consensus_message_validation.py::test_bundle_seq_mismatch_rejected` |
| CE-007 | 同一 `bundle_hash` 的 fee bump 先后经两个 non-winner 转发到 winner | 这条是“端侧重试/服务端重发”最像真的轻量 replacement 场景，既不能引入新 sidecar，也不能把 sender receipt 对账打坏 | `已验证安全`：winner 会保留同 `bundle_hash` 的更高 fee 版本，最终 sender receipt 能正常确认，block 中记录的也是 bump 后 fee | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_mvp_window_accepts_same_bundle_fee_bump_forwarded_from_non_winners` |
| CE-008 | 同一 `bundle_hash` 已 fee bump 后，旧 fee 包又从另一个 non-winner 乱序重放回来 | 这条专门验证乱序/重复转发下 winner 是否会被旧 envelope 降级，适合模拟真实网络抖动和端侧重试 | `已验证安全`：旧 fee 重放会被以 `replacement bundle fee too low` 拒绝，winner 保持最高 fee 版本直至出块 | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_mvp_window_rejects_old_fee_replay_after_forwarded_fee_bump` |
| CE-009 | 同一 `bundle_hash` 经多次提价后，较旧 fee 包在更晚时刻才到达 winner 路径 | 这条更接近真实“端侧多次重试 + 网络延迟反转”的长序列时序，专门检查 winner 是否始终保留最高 fee envelope | `已验证安全`：`fee 0 -> fee 2 -> fee 4 -> 旧 fee 1` 的长链条下，winner 最终仍保持 `fee=4`，旧包不会导致回退 | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_mvp_window_keeps_highest_fee_after_multiple_forwarded_bumps` |
| CE-010 | recipient 是 value 的旧 owner，sender 若仍发送全量 prior witness，就会浪费端侧传输与验证成本 | 这类问题不会直接打坏状态机，却会在真实端侧运行时持续放大带宽和 CPU 消耗，属于“逻辑正确但资源约束失守”的隐蔽缺陷 | `已发现并修复`：sender 现在只根据自己本地 witness/history 直接裁剪到 exact-range checkpoint，不再增加 sender→recipient 的额外探测通信；recipient 仅用本地历史与 checkpoint 验证 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_delivery_to_old_owner_uses_local_checkpoint_trim_without_extra_query`；`EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_first_hop_delivery_keeps_full_anchor_when_recipient_never_owned_value`；实现位于 `EZ_V2/wallet.py`、`EZ_V2/network_host.py` |
| NX-005 | 共识节点在 `CommitQC` 已形成但 receipt 尚未完全发出时崩溃重启 | 设计要求 final -> confirmed seq -> receipt cache -> receipt deliver 的顺序固定，必须证明重启点不会把 sender 卡进永久 pending | `已验证安全`：winner 在本地 commit 落盘后即使在 receipt 派发前崩溃，重启后 sender 仍可通过 `receipt_req` 恢复 receipt 与 block | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_recovery.py::test_flow_mvp_commit_survives_restart_when_winner_crashes_before_receipt_delivery` |
| NX-006 | 旧磁盘状态混跑：旧 validator set、旧 fetched block、旧 account pending bundle 与新链状态混合启动 | 本地联调时很常见，容易误判成协议 bug，实际上是 dirty-state/restart bug | `已发现并修复`：account recovery 现在会在链回退/同高分叉时清理脏 `fetched_blocks`，并在检测到链重置时清掉旧 `pending_bundle`，避免旧链状态混入新链继续运行 | `EZ_Test/test_ez_v2_network_recovery.py::test_restart_discards_stale_cached_blocks_when_remote_chain_is_shorter`；`EZ_Test/test_ez_v2_network_recovery.py::test_recovery_clears_stale_pending_bundle_after_detected_chain_reset`；实现位于 `EZ_V2/network_host.py` |
| NX-017 | Checkpoint 精确区间匹配导致 Value 分裂后 Checkpoint 失效 | 容易把“当前 MVP 只支持 exact-range”误判成值会被卡死；需要确认 split 后至少会安全回退，而不是把 Value 变成不可验证垃圾 | `已验证安全`：当前 MVP 仍只支持 exact-range checkpoint，partial overlap / containment 不复用 checkpoint；但 split 后会回退为完整 prior witness，值仍可继续验证与流转，不会卡死 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_checkpoint_partial_overlap_cannot_reuse_exact_range_checkpoint`；`EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_split_value_falls_back_to_full_witness_when_exact_checkpoint_no_longer_matches` |
| NX-018 | MVP Sortition VRF 密钥确定性推导 | 这是 MVP 本地网络里最危险的身份伪造面，必须避免“只知道 `validator_id` 就能推私钥” | `已发现并修复`：MVP validator 的 vote/VRF key 现在改为基于本地持久化 cluster secret 推导，同一 cluster 重启保持稳定，不同 cluster 即使 `validator_id` 相同也不会得到同一私钥 | `EZ_Test/test_ez_v2_network_sortition.py::test_mvp_validator_keys_depend_on_persisted_cluster_secret`；实现位于 `EZ_V2/network_host.py` |

## 下一批高优先级待补

| ID | 反例 | 风险点 |
| --- | --- | --- |
| NX-001 | 同一原始 bundle 在 winner 尚未出块前，被重复投递到 winner 和多个 non-winner | 需要确认 forwarding、pending 去重、最终清池都不会把同一 bundle 留成“未来炸弹” |
| NX-002 | 同一 sender 的“同 sidecar fee bump”更长窗口幂等性 | 当前已验证单次 bump、一次旧包重放、以及一条较短多次提价链安全，但还需要继续确认 follower 同步、重复广播、以及跨块窗口下不会保留旧 envelope 或重复广播 |
| NX-003 | winner 已本地 final，但 `receipt_deliver`、`block_announce`、`transfer_package_deliver` 的对端部分失败 | 需要确认 partial delivery 不会污染已成功的状态提交，也不会让 follower 长期保留脏 mempool |
| NX-004 | follower 长时间收不到 `block_announce`，只在若干块后通过 `chain_state`/`block_fetch` 追平 | 这是“慢节点 + stale mempool”场景，容易藏重复打包或错误删除 |
| NX-007 | 同一账户并发提交多个 malformed / truncated / wrong-chain bundle | 需要把“错误输入防御”和“正常路径不被拖死”一起验证，防止出现错误输入堵塞合法 bundle |
| NX-008 | 单个 account 节点长期只盯住一个 consensus peer，其他 peer 已切换高度或不可达 | 这本质上是本地版 eclipse / stale-view 问题，需要验证 peer 健康检查、重试、重连和追平行为 |
| NX-009 | exact-range checkpoint 之外的 split / partial overlap return | 当前 sender-local 裁剪已经收口到 exact-match；部分区间复用仍然是协议边界问题，不能为了省 witness 直接做隐式推断 |
| NX-010 | `BundlePool.submit` 未强制 low-s 签名验证 | 协议草案 §4.2/§19.2 明确要求"强制 low-s"，但 `verify_bundle_envelope` → `verify_digest_secp256k1` 全链路无 low-s 检查。签名可塑性攻击：同一 bundle 存在两个合法签名 (s, n-s)，攻击者可用 high-s 版本在不同 consensus 节点制造 mempool 视角分歧 |
| NX-011 | `apply_block` 未验证 bundle 的 `expiry_height` | `BundlePool.submit` 拒绝过期 bundle，但 `apply_block`（`chain.py:464-555`）对收到的区块中 bundle 完全不检查 expiry_height；恶意 proposer 可手工拼入已过期 bundle，所有 follower 都会接受 |
| NX-012 | Wallet 接受 Receipt 时未验证 `state_root` 属于已知 canonical 区块 | `on_receipt_confirmed`（`wallet.py:571-606`）只验证 SMT proof 对 `receipt.header_lite.state_root` 成立，不检查该 state_root 是否对应链上真实区块；恶意 consensus 节点可构造假 state_root + SMT proof 生成看起来合法的 Receipt |
| NX-013 | 多接收人 TransferPackage 投递全有或全无 | `_on_receipt`（`network_host.py:1698-1709`）在循环中对不在线 recipient 的 `_find_peer_id_by_address` 抛异常，导致所有 recipient（含在线的）都收不到 TransferPackage，sender 的 Receipt 处理整体失败 |
| NX-014 | `_on_block_announce` 静默忽略分叉信息 | `network_host.py:556-557` 用 `announced_height <= current_height` 判断已追平，不检查 block_hash 是否一致；follower 无法检测到同高度不同分叉的存在 |
| NX-015 | `_tx_hash_hex` 使用 `repr()` 而非 canonical encoding | `network_host.py:1848-1849` 的 `repr(tx)` 依赖 Python 版本和 dataclass 实现细节，违反协议草案 §4.3；跨版本/跨实现 tx hash 不一致会导致交易追踪/索引/去重失败 |
| NX-016 | Sidecar GC 与 Record 持久化存在时序竞争 | `_persist_records`（`wallet.py:110-113`）先 `replace_value_records`（清零旧引用）再 `recompute_sidecar_ref_counts`，中间窗口若 GC 触发，正在被新记录引用的 sidecar 可能因 ref_count 暂时为 0 被误删，导致 witness 无法重建 |
| NX-019 | PRECOMMIT QC 形成后立即 prune vote log 可能丢失 COMMIT 上下文 | `consensus/core.py:97-100` 在 PRECOMMIT QC 形成时 prune `round <= qc.round` 的投票记录；崩溃恢复后无法重建 COMMIT 投票记录，导致需要重新走一轮 timeout |

## 协议级安全缺陷（已确认）

| ID | 缺陷 | 严重性 | 描述 | 协议修复方向 |
| --- | --- | --- | --- | --- |
| PL-001 | Sidecar GC 导致 re-received Value 的 Witness 不完整 | **高** | 场景：(1) Alice 将 Value V 转 Bob，附全量 Witness；(2) Bob 验证接受 V，创建 Checkpoint C；(3) Bob 将 V 转 Charlie，Witness 按 C 裁剪；(4) Bob 本地 pre-C 的 sidecar refcount 归零并被 GC；(5) Charlie 将 V 转回 Bob，检测到 Bob 是旧 owner 且有 C，仅发 C 之后的 witness 切片；(6) Bob 接受 V 后欲转 Dave，但 Dave 不信任 C（C 是 Bob 自己的 checkpoint），需要全量 Witness 到 GenesisAnchor；(7) Bob 本地 sidecar 已被删，无法重建全量 Witness → V 变成死值 | 协议须补充"旧 owner 重新接收 Value 时的 witness 完整性恢复机制"：recipient 有权向 sender 索要完整（未裁剪的）witness 以恢复本地 sidecar 存储；sender 有义务提供。详见 `EZchain-V2-protocol-draft.md` 新增 §15.9、§20 问题 12 |

## 条件触发类（BFT 共识下暂无需担心）

| ID | 反例 | 触发条件 | 说明 |
| --- | --- | --- | --- |
| CT-001 | Wallet 无 Receipt 确认深度检查 | 底层共识为概率性确认（PoW/PoS），区块可能被重组 | 协议草案 §18.4 要求"用户侧 SHOULD 仅在区块足够确认后进行正式 P2P 收款接受"，但 `on_receipt_confirmed` Receipt 一到即全盘接受，无任何 finality depth 检查。当前 EZchain-V2 采用 BFT 确定性共识（HotStuff-variant），区块一旦 CommitQC 形成即不可回滚，此问题暂不触发。若未来切换至概率性共识，必须补此防线 |

## 待解类（暂无已知解决方案）

| ID | 反例 | 难点 | 当前状态 |
| --- | --- | --- | --- |
| US-001 | Witness 递归无深度限制（超大 Witness DoS） | 恶意 sender 可通过多账户间反复转账构造极深 PriorWitnessLink 链，拖垮 recipient 验证资源。协议草案 §19.10 提到需"钱包设置最大验证预算"但代码无实现。然而，若 recipient 拒绝过深的 witness，会直接影响 Value 流通性——合法的高流转 Value 也会被拒绝。尚未找到在"保护 recipient"与"不损害流通性"之间的平衡方案 | 暂不处理，继续跟踪 |

## 外部资料带来的设计提醒

这些资料不是直接照搬到 EZchain-V2，而是帮助我们挑“值得本地化联调”的攻击面：

- [EIP-155: Simple replay attack protection](https://eips.ethereum.org/EIPS/eip-155)
  - 提醒我们：`chain_id`、签名域分隔、sender 序号必须作为重放防线的一部分，不能只依赖“这笔交易看起来像发过”。
- [Bitcoin Core Developer Documentation: Mempool Replacements](https://casey.github.io/bitcoin/doc/policy/mempool-replacements.html)
  - 提醒我们：如果允许 replacement，就必须把 fee 规则、带宽/DoS 边界、冲突集处理写清楚并测试，而不能让“同 seq 覆盖”变成隐式行为。
- [Eclipse Attacks on Bitcoin’s Peer-to-Peer Network (USENIX Security 2015)](https://www.usenix.org/conference/usenixsecurity15/technical-sessions/presentation/heilman)
  - 提醒我们：本地联调不能只看“单 peer 可通”，还要看 stale peer、单 peer 依赖、重连、追平、视图受限后的错误行为。
- [HotStuff: BFT Consensus in the Lens of Blockchain](https://arxiv.org/abs/1803.05069)
  - 提醒我们：leader failover、重复投票、过时 proposal、跨轮次状态恢复这类问题，必须用多轮、多节点、跨重启的方式测，不然很容易只测到 happy path。

## 使用建议

- 新增反例前，先写一句“为什么这是真反例，而不是误用例”。
- 每条反例优先落到最小稳定回归，不先写大而全脚本。
- 一旦某条反例真的打出了 bug，优先补自动化测试，再决定是否扩展文档描述。
