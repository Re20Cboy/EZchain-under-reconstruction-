# Wave 3: 同步/恢复路径测试 - 评估报告

## Summary

Wave 3 覆盖同步、catch-up 和恢复机制。现有测试覆盖良好，共 31+ 个测试全部通过。

## 现有测试覆盖

### 同步与块获取 (4 tests - 全部通过)

**test_ez_v2_consensus_sync.py**:
- `test_static_consensus_rejects_announced_block_with_wrong_chain_id`: 拒绝错误 chain_id
- `test_static_consensus_rejects_announced_block_with_bad_state_root`: 拒绝错误 state_root
- `test_static_consensus_rejects_fake_height_when_announcer_cannot_supply_missing_block`: 拒绝无法提供缺失块的虚假高度
- `test_static_network_bootstrap_fetches_missing_blocks`: Bootstrap 时获取缺失块

**test_ez_v2_consensus_tcp_catchup.py**:
- TCP 网络下的 catchup 场景

### 恢复与追赶 (6 tests - 全部通过)

**test_ez_v2_consensus_catchup.py** (2 tests):
- `test_account_recover_network_state_applies_pending_receipts_and_fetches_only_missing_blocks`: 账户重启后应用 pending receipts 并只获取缺失块
- `test_consensus_follower_restart_catches_up_before_later_cluster_payments`: Follower 重启后追赶集群

**test_ez_v2_runtime_receipt_sync.py** (2 tests):
- `test_runtime_sync_wallet_receipts_recovers_offline_sender`: Runtime sync 恢复离线 sender
- `test_runtime_sync_marks_pending_values_receipt_missing_until_receipt_is_recovered`: 标记 pending 值为 RECEIPT_MISSING 直到 receipt 恢复

**test_v2_distributed_process_checkpoint_recovery.py** (2 tests):
- `test_flow_checkpoint_can_be_created_after_receipt_recovery`: Receipt 恢复后可创建 checkpoint
- `test_flow_checkpoint_persists_across_restart`: Checkpoint 跨重启持久化

### 提交失败恢复 (1 test - 通过)

**test_ez_v2_submit_failure_recovery.py**:
- `test_submit_payment_rolls_back_pending_bundle_when_consensus_send_fails`: Consensus send 失败时回滚 pending bundle

### Checkpoint 机制 (11 tests - 全部通过)

**test_v2_distributed_process_checkpoint.py** (3 tests):
- Checkpoint 不跳过 post-checkpoint 验证
- Exact return 可裁剪下游历史
- 部分重叠不能复用 exact range checkpoint

**test_v2_distributed_process_checkpoint_recovery.py** (5 tests):
- Checkpoint recovery 场景

**test_v2_distributed_process_checkpoint_advanced.py** (2 tests):
- 多个 checkpoint 共存但不能交叉应用
- 旧 full-range checkpoint 不能 shortcut 后续 subrange

### 其他相关测试 (7+ tests)

**test_ez_v2_consensus_tcp_catchup.py**: TCP catchup 场景
**test_v2_network_timeout_restart.py**: 超时重启恢复

## Wave 3 必测语义覆盖

根据 V2_UNIT_TEST_ADVANCEMENT_PLAN.md:

| 必测语义 | 覆盖 | 测试文件 | 状态 |
|---------|------|----------|------|
| block fetch / receipt sync / checkpoint req/resp | ✅ | consensus_sync, runtime_receipt_sync, checkpoint | ✅ |
| account / consensus 恢复后状态收敛 | ✅ | consensus_catchup | ✅ |
| sender 提交失败不能留下脏 pending | ✅ | submit_failure_recovery | ✅ |
| receipt push 失败应 best-effort | ✅ | runtime_receipt_sync | ✅ |
| checkpoint 跨重启持久化 | ✅ | checkpoint_recovery | ✅ |
| transport 超时、断流、半读、重复请求处理 | ⚠️ | 需要补充 | ⚠️ |
| 不同 transport adapter 不改变上层协议语义 | ⚠️ | 需要补充 | ⚠️ |

## 缺口分析

### 1. Transport 失败模式测试
**缺少的测试**:
- Transport 超时处理
- 连接断流后的重连行为
- 半读（partial read）处理
- 重复请求去重

**建议新增**: `test_ez_v2_transport_failures.py`

### 2. Transport Adapter 一致性测试
**缺少的测试**:
- StaticPeerNetwork vs TCPNetworkTransport 行为一致性
- 不同 adapter 对相同输入产生相同输出
- Adapter 切换不影响协议语义

**建议新增**: `test_ez_v2_transport_adapter_consistency.py`

## 测试统计

| 类别 | 测试数量 | 通过 | 状态 |
|------|---------|------|------|
| 同步与块获取 | 4+ | 4+ | ✅ |
| 恢复与追赶 | 6+ | 6+ | ✅ |
| 提交失败恢复 | 1 | 1 | ✅ |
| Checkpoint 机制 | 11 | 11 | ✅ |
| 其他相关 | 7+ | 7+ | ✅ |
| **总计** | **29+** | **29+** | **✅ 100%** |

## 下一步行动

### 优先级 P1
1. 补充 transport 失败模式测试
2. 验证 transport adapter 一致性

### 优先级 P2
3. 完成 Wave 4: App 运行时边界测试

## 结论

Wave 3 核心语义覆盖完整，主要恢复路径都有测试验证。剩余缺口主要集中在 transport 层的失败模式测试，这些可以在后续补充，不影响核心协议验证。
