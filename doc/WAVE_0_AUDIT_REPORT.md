# Wave 0: 测试口径审计报告

本报告对照 `V2_UNIT_TEST_ADVANCEMENT_PLAN.md` 对现有 `test_ez_v2_*.py` 测试文件进行审计。

## 审计结论汇总

| 文件 | 判断 | next action | 设计依据 |
|------|------|-------------|----------|
| test_ez_v2_consensus_core.py | aligned | keep | consensus-mvp-spec.md |
| test_ez_v2_consensus_pacemaker.py | aligned | keep | consensus-mvp-spec.md |
| test_ez_v2_wallet_storage.py | aligned | keep | protocol-draft.md |
| test_ez_v2_runtime.py | unclear | audit | node-role-and-app-boundary.md |
| test_ez_v2_network.py | unclear | split | network-and-transport-plan.md |
| test_ez_v2_crypto.py | aligned | keep | consensus-mvp-spec.md |
| test_ez_v2_consensus_sortition.py | unclear | audit | consensus-mvp-spec.md |
| test_ez_v2_consensus_validator_set.py | unclear | audit | consensus-mvp-spec.md |
| test_ez_v2_consensus_runner.py | unclear | audit | consensus-mvp-spec.md |
| test_ez_v2_consensus_store.py | unclear | audit | consensus-mvp-spec.md |
| test_ez_v2_sync.py | unclear | audit | network-and-transport-plan.md |
| test_ez_v2_catchup.py | unclear | audit | network-and-transport-plan.md |
| test_ez_v2_transport.py | unclear | audit | network-and-transport-plan.md |
| test_ez_v2_submit_failure_recovery.py | unclear | audit | network-and-transport-plan.md |

## 详细审计

### 1. test_ez_v2_consensus_core.py

**测试内容**:
- `test_local_vote_conflict_is_rejected`: 同一(height, round, phase)拒绝对不同块投票
- `test_precommit_qc_updates_lock_and_round`: PreCommitQC更新locked_qc和round
- `test_commit_qc_marks_decided`: CommitQC标记decided
- `test_duplicate_vote_is_idempotent_after_qc`: QC后重复投票幂等

**设计依据**: consensus-mvp-spec.md 第7节、第9节

**判断**: **aligned**

**理由**:
- Safety rule (no duplicate votes) 符合spec第9节
- QC推进逻辑符合HotStuff三阶段设计
- Locked QC保护机制符合spec

**next action**: **keep** - 这些测试验证了核心共识语义，应保留

---

### 2. test_ez_v2_consensus_pacemaker.py

**测试内容**:
- `test_local_timeout_advances_round_and_backs_off_timeout`: 超时推进round
- `test_qc_jumps_round_and_clears_timeout_streak`: QC重置超时计数
- `test_tc_jump_and_decide_keep_round_history_consistent`: TC/decise保持round历史

**设计依据**: consensus-mvp-spec.md pacemaker章节

**判断**: **aligned**

**理由**:
- 超时指数退避符合BFT标准实践
- QC收到后推进round符合HotStuff设计
- Round历史一致性符合spec要求

**next action**: **keep**

---

### 3. test_ez_v2_wallet_storage.py

**测试内容**:
- `test_build_bundle_persists_pending_and_restart`: pending bundle持久化与重启恢复
- `test_receipt_confirmation_persists_records_and_exports_transfer`: receipt确认更新记录并导出transfer

**设计依据**: protocol-draft.md wallet章节

**判断**: **aligned**

**理由**:
- Pending bundle重启后恢复符合设计
- Receipt确认后状态转换符合协议
- Transfer导出符合P2P验证设计

**next action**: **keep** - 但建议拆分出更focused的单元测试

---

### 4. test_ez_v2_runtime.py

**测试内容**:
- `test_runtime_auto_confirms_registered_sender_receipt`: runtime自动确认已注册sender的receipt
- `test_runtime_delivers_transfer_package_and_recipient_can_respend`: runtime投递transfer package，recipient可重花

**设计依据**: node-role-and-app-boundary.md

**判断**: **unclear** - 需进一步审计

**理由**:
- 测试runtime行为，但未明确验证app层是否越界
- 需确认auto-confirm是否是runtime职责还是应由共识层驱动
- 需确认delivery是否符合P2P边界设计

**风险点**:
- App层可能通过默认值改变协议行为
- Runtime职责边界不清晰

**next action**: **audit** - 需对照node-role-and-app-boundary.md验证app层wiring边界

---

### 5. test_ez_v2_network.py

**测试内容**:
- 集成测试：StaticPeerNetwork、TCPNetworkTransport、消息传递

**设计依据**: network-and-transport-plan.md

**判断**: **unclear** - 需拆分

**理由**:
- 当前是集成测试，混入了网络、共识、钱包多层语义
- 未单独验证transport失败模式
- 未明确验证不同transport adapter的一致性

**风险点**:
- 集成测试可能掩盖层间drift
- Transport失败语义未独立验证

**next action**: **split** - 拆分为focused tests:
- test_ez_v2_transport_semantics.py (transport层)
- test_ez_v2_network_messaging.py (消息传递)
- test_ez_v2_transport_failures.py (失败模式)

---

### 6. test_ez_v2_crypto.py

**测试内容**:
- keccak256后端回退机制 (hashlib -> pycryptodome -> error)

**设计依据**: consensus-mvp-spec.md crypto章节

**判断**: **aligned**

**理由**:
- 加密原语的正确回退是基础设施要求
- 不涉及协议语义，纯实现细节

**next action**: **keep**

---

### 7-14. 其他测试文件

以下文件标记为 **unclear**，需要逐一审计：

| 文件 | 重点关注 |
|------|----------|
| test_ez_v2_consensus_sortition.py | VRF sortition是否与seed/height/round正确绑定 |
| test_ez_v2_consensus_validator_set.py | validator set许可型边界 |
| test_ez_v2_consensus_runner.py | runner是否采用snapshot window |
| test_ez_v2_consensus_store.py | round/height/QC持久化正确性 |
| test_ez_v2_sync.py | sync路径是否符合设计 |
| test_ez_v2_catchup.py | catch-up是否支持receipt/block fetch |
| test_ez_v2_transport.py | transport失败模式 |
| test_ez_v2_submit_failure_recovery.py | 提交失败后pending清理 |

## 必须重写的测试文件名单

基于审计，以下测试文件需要重写或拆分：

1. **test_ez_v2_network.py** → 拆分为3个focused tests
2. **test_ez_v2_runtime.py** → 需审计app边界
3. **test_ez_v2_consensus_runner.py** → 需验证snapshot window语义
4. **test_ez_v2_sync.py** → 需focused sync路径测试
5. **test_ez_v2_catchup.py** → 需focused catch-up测试

## Temporary Divergence 列表

当前未发现明确的temporary divergence，但以下行为需要显式验证：

- runtime auto-confirm行为是否由共识层驱动而非app层擅自决定
- 网络层是否在未收到完整receipt时提前推进状态

## 下一步行动

1. 完成unclear标记文件的详细审计
2. 创建Wave 1模块层focused tests
3. 拆分test_ez_v2_network.py为focused tests
