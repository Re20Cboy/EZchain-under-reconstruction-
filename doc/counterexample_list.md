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
| NX-001 | 同一原始 bundle 在 winner 尚未出块前，被重复投递到 winner 和多个 non-winner | 这是端侧重试、forwarding 重放、以及多入口接入最常见的真实时序之一，必须确认重复投递不会把 pending 变成“未来炸弹” | `已发现并修复`：完全相同的 `submission` 现在按幂等重放处理，winner 在整个窗口内只保留 1 份 pending；commit 后各节点 pool 清空，旧包再重放仍按 stale seq 拒绝 | `EZ_Test/test_ez_v2_chain_core.py::test_bundle_pool_accepts_identical_replay_idempotently`；`EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_mvp_window_deduplicates_identical_submission_replays_before_commit`；实现位于 `EZ_V2/chain.py` |
| NX-002 | 同一 sender 的“同 sidecar fee bump”更长窗口幂等性 | 需要确认更长 fee bump 链、commit 后旧包重放、以及 follower 重启后重放都不会让旧 envelope 回流到新窗口 | `已验证安全`：`fee 0 -> 2 -> 4` 后，commit 后旧 fee 重放与 follower 重启后的旧包重放都按 stale seq 拒绝；新 seq 提交不受旧窗口残留污染 | `EZ_Test/test_ez_v2_network_tcp_cluster.py::test_tcp_mvp_window_keeps_highest_fee_after_commit_replay_and_follower_restart` |
| NX-003 | winner 已本地 final，但 `receipt_deliver`、`block_announce`、`transfer_package_deliver` 的对端部分失败 | 这是最典型的“本地已成功，后续 fanout 局部失败”分布式恢复面，必须确认成功副作用不会被失败 fanout 反向污染 | `已发现并修复`：legacy 路径里的 receipt push 与 MVP 路径里的 finalize fanout 现在都改成最佳努力；sender 可经 `receipt_req` 恢复 receipt，online recipient 不受 offline recipient 影响，掉队 follower 可事后追平 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_adversarial.py::test_flow_mvp_commit_survives_partial_receipt_announce_and_finalize_failures`；实现位于 `EZ_V2/network_host.py` |
| NX-004 | follower 长时间收不到 `block_announce`，只在若干块后通过 `chain_state`/`block_fetch` 追平 | 这条专门覆盖“慢节点 + missed announce + stale pending”组合，检查追平是否既补块又清掉旧本地状态 | `已验证安全`：连续错过多块 announce 后，follower 仍可通过 `chain_state`/`block_fetch` 追平多块，并在 `apply_block` 过程中清掉旧 pending；旧 bundle 再重放仍按 stale seq 拒绝 | `EZ_Test/test_ez_v2_network_recovery.py::test_recovery_fetches_multiple_missing_blocks_and_clears_stale_pending_after_missed_announces` |
| NX-005 | 共识节点在 `CommitQC` 已形成但 receipt 尚未完全发出时崩溃重启 | 设计要求 final -> confirmed seq -> receipt cache -> receipt deliver 的顺序固定，必须证明重启点不会把 sender 卡进永久 pending | `已验证安全`：winner 在本地 commit 落盘后即使在 receipt 派发前崩溃，重启后 sender 仍可通过 `receipt_req` 恢复 receipt 与 block | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_recovery.py::test_flow_mvp_commit_survives_restart_when_winner_crashes_before_receipt_delivery` |
| NX-006 | 旧磁盘状态混跑：旧 validator set、旧 fetched block、旧 account pending bundle 与新链状态混合启动 | 本地联调时很常见，容易误判成协议 bug，实际上是 dirty-state/restart bug | `已发现并修复`：account recovery 现在会在链回退/同高分叉时清理脏 `fetched_blocks`，并在检测到链重置时清掉旧 `pending_bundle`，避免旧链状态混入新链继续运行 | `EZ_Test/test_ez_v2_network_recovery.py::test_restart_discards_stale_cached_blocks_when_remote_chain_is_shorter`；`EZ_Test/test_ez_v2_network_recovery.py::test_recovery_clears_stale_pending_bundle_after_detected_chain_reset`；实现位于 `EZ_V2/network_host.py` |
| NX-007 | 同一账户并发提交多个 malformed / truncated / wrong-chain bundle | 错误输入不该污染 handler 或把后续正常提交拖死，尤其不能让坏 payload 先把 account 侧/共识侧状态弄脏 | `已发现并修复`：`_on_bundle_submit` 现在会先校验 `submission` 类型再处理，malformed payload 返回 `missing_submission`；连续 wrong-chain / bad-signature / malformed 提交后，共识端不会残留脏 pending，合法 bundle 仍可继续上链 | `EZ_Test/EZ_V2_New_Test/test_v2_consensus_message_validation.py::test_repeated_malformed_bundle_attempts_do_not_block_later_valid_submit`；实现位于 `EZ_V2/network_host.py` |
| NX-008 | 单个 account 节点长期只盯住一个 consensus peer，其他 peer 已切换高度或不可达 | 这本质上是本地版 eclipse / stale-view 问题，必须确认 stale-but-reachable、missing-based retry、以及重启后的首选 peer 恢复都能收口 | `已发现并修复`：account 现在会在 `receipt_req` / `block_fetch` 返回 `missing` 时刷新最佳 peer 并重试一次；若已知 preferred peer 落后于本地已知链，也会先晋升更高 peer；新首选会持久化到 `state_path` 并在重启后恢复 | `EZ_Test/test_ez_v2_network_submission_flows.py::test_refresh_chain_state_promotes_higher_peer_when_primary_is_stale_but_reachable`；`EZ_Test/test_ez_v2_network_submission_flows.py::test_sync_pending_receipts_promotes_higher_peer_after_missing_from_stale_primary`；`EZ_Test/test_ez_v2_network_submission_flows.py::test_fetch_block_retries_after_missing_from_stale_primary`；`EZ_Test/test_ez_v2_network_submission_flows.py::test_recover_network_state_persists_promoted_peer_order_across_restart`；实现位于 `EZ_V2/network_host.py` |
| NX-009 | exact-range checkpoint 之外的 split / partial overlap return | 当前 sender-local 裁剪已经收口到 exact-match；需要确认“不能复用 checkpoint”时会安全回退，而不是偷做隐式推断或把值卡死 | `已验证安全`：MVP 仍只支持 exact-range checkpoint；split / partial overlap return 不复用 checkpoint，而是回退为完整 prior witness，不增加额外查询，也不会让 Value 失去可流转性 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_delivery_to_old_owner_uses_local_checkpoint_trim_without_extra_query`；`EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_split_value_falls_back_to_full_witness_when_exact_checkpoint_no_longer_matches`；`EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_checkpoint_partial_overlap_cannot_reuse_exact_range_checkpoint` |
| NX-010 | `BundlePool.submit` 未强制 low-s 签名验证 | 协议草案要求 low-s，不补这条很容易把“签名可塑性”误判成实现漏检 | `已验证安全`：当前 `verify_digest_secp256k1()` 已拒绝 high-s 签名；显式把 low-s 翻成 `(r, n-s)` 后，无论 chain submit 还是 network submit 都会被拒绝 | `EZ_Test/EZ_V2_New_Test/test_v2_consensus_message_validation.py::test_high_s_bundle_signature_is_rejected_by_chain_and_network` |
| NX-011 | `apply_block` 未验证 bundle 的 `expiry_height` | follower 不能只信 proposer，必须在收块时再次检查过期语义 | `已发现并修复`：`apply_block()` 现在会拒绝 `expiry_height < block.height` 的 bundle，恶意 proposer 手工拼入过期 bundle 不再被 follower 接受 | `EZ_Test/test_ez_v2_chain_core.py::test_apply_block_rejects_bundle_expired_at_block_height`；实现位于 `EZ_V2/chain.py` |
| NX-012 | Wallet 接受 Receipt 时未验证 `state_root` 属于已知 canonical 区块 | 只验证 proof 自洽还不够，必须同时确认该 `HeaderLite` 属于本地已知 canonical 链 | `已发现并修复`：wallet 现在要求 receipt 的 `height + block_hash + state_root` 已被本地认作 canonical；伪造但自洽的假 header/proof 会被拒绝 | `EZ_Test/test_ez_v2_wallet_storage.py::test_receipt_confirmation_rejects_unknown_canonical_header_even_with_valid_proof`；实现位于 `EZ_V2/wallet.py`、`EZ_V2/network_host.py`、`EZ_V2/runtime_v2.py` |
| NX-013 | 多接收人 TransferPackage 投递全有或全无 | 一名离线 recipient 不该拖死在线 recipient，也不该把 sender 的 receipt 应用整体打断 | `已发现并修复`：`_on_receipt()` 现在按 recipient 最佳努力投递，离线 recipient 只记 partial delivery，不再阻断在线 recipient 收包 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_adversarial.py::test_flow_receipt_delivery_survives_missing_recipient_handler`；实现位于 `EZ_V2/network_host.py` |
| NX-014 | `_on_block_announce` 静默忽略分叉信息 | 同高度不同 `block_hash` 不能被当成“已经追平”吞掉，否则 follower 看不到分叉冲突 | `已发现并修复`：`_on_block_announce()` 现在会显式拒绝同高度不同 `block_hash` 的 announce，不再静默忽略分叉 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_adversarial.py::test_flow_block_announce_rejects_same_height_conflicting_hash`；实现位于 `EZ_V2/network_host.py` |
| NX-015 | `_tx_hash_hex` 使用 `repr()` 而非 canonical encoding | 交易哈希必须跨 Python 版本与实现稳定，否则索引/追踪/去重都会飘 | `已发现并修复`：交易哈希现在统一基于 canonical encoding 计算，不再依赖 `repr()` | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_adversarial.py::test_tx_hash_uses_canonical_encoding`；实现位于 `EZ_V2/network_host.py` |
| NX-016 | Sidecar GC 与 Record 持久化存在时序竞争 | 本地 GC 与 record 落盘之间若暴露窗口，会把仍被新记录引用的 sidecar 误删 | `已发现并修复`：record 替换与 sidecar refcount 重算现在在同一受锁路径内完成，GC 不能再插入中间窗口误删 sidecar | `EZ_Test/test_ez_v2_wallet_storage.py::test_persist_records_keeps_sidecar_alive_when_gc_races_before_refcount_recompute`；实现位于 `EZ_V2/storage.py`、`EZ_V2/wallet.py` |
| NX-017 | Checkpoint 精确区间匹配导致 Value 分裂后 Checkpoint 失效 | 容易把“当前 MVP 只支持 exact-range”误判成值会被卡死；需要确认 split 后至少会安全回退，而不是把 Value 变成不可验证垃圾 | `已验证安全`：当前 MVP 仍只支持 exact-range checkpoint，partial overlap / containment 不复用 checkpoint；但 split 后会回退为完整 prior witness，值仍可继续验证与流转，不会卡死 | `EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_checkpoint_partial_overlap_cannot_reuse_exact_range_checkpoint`；`EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint.py::test_flow_split_value_falls_back_to_full_witness_when_exact_checkpoint_no_longer_matches` |
| NX-018 | MVP Sortition VRF 密钥确定性推导 | 这是 MVP 本地网络里最危险的身份伪造面，必须避免“只知道 `validator_id` 就能推私钥” | `已发现并修复`：MVP validator 的 vote/VRF key 现在改为基于本地持久化 cluster secret 推导，同一 cluster 重启保持稳定，不同 cluster 即使 `validator_id` 相同也不会得到同一私钥 | `EZ_Test/test_ez_v2_network_sortition.py::test_mvp_validator_keys_depend_on_persisted_cluster_secret`；实现位于 `EZ_V2/network_host.py` |
| NX-019 | PRECOMMIT QC 形成后立即 prune vote log 可能丢失 COMMIT 上下文 | 这类恢复面很容易被“静态看起来危险”误判，需要真实做崩溃恢复回归 | `已验证安全`：当前实现是按 `< qc.round` 而不是 `<= qc.round` prune，崩溃重启后仍能用剩余 COMMIT votes 重建 `CommitQC`，不会被迫先走 timeout | `EZ_Test/EZ_V2_New_Test/test_v2_consensus_safety_persistence.py::test_commit_votes_survive_precommit_prune_and_restart` |

## 协议级边界（当前实现已规避，未来瘦身路径仍需单独起方案）

| ID | 缺陷 | 严重性 | 描述 | 协议修复方向 |
| --- | --- | --- | --- | --- |
| PL-001 | Sidecar GC 导致 re-received Value 的 Witness 不完整 | **高** | 协议草案里的风险场景是：旧 owner 基于本地 checkpoint 收回裁剪过的 witness 后，若 pre-checkpoint sidecar 已被删，就可能无法再向一个不信任该 checkpoint 的第三方发送全量 witness | `已验证安全（当前实现）`：当前钱包会长期保留 archived record 里的完整 witness，旧 owner re-receive 时也会把 `CheckpointAnchor` 重新水合为本地完整 prior witness；因此即使执行 sidecar GC，当前实现里值仍可继续转给不信任该 checkpoint 的第三方。若未来做更激进的 witness/sidecar 瘦身，才需要引入 `WitnessCompletionReq/Resp` 一类协议扩展。证据：`EZ_Test/EZ_V2_New_Test/test_v2_distributed_process_checkpoint_recovery.py::test_flow_old_owner_can_rerespend_after_checkpoint_trim_and_sidecar_gc`；协议提醒仍见 `EZchain-V2-protocol-draft.md` §15.9、§20 问题 12 |

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
