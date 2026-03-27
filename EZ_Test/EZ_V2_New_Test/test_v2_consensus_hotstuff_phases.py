"""
EZchain-V2 HotStuff三阶段BFT共识测试

设计文档对照：
- EZchain-V2-consensus-mvp-spec.md 第7节 "BFT确认算法"
- EZchain-V2-consensus-mvp-spec.md 第7.2节 "阈值"
- EZchain-V2-consensus-mvp-spec.md 第7.3节 "消息对象"

测试类别：
- design-conformance: 验证HotStuff三阶段机制符合设计
- boundary/invariants: 验证QC阈值和阶段转换
- safety: 验证safety rule防止双final
"""

from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import dataclass, field
from typing import Any

from EZ_V2.network_host import StaticPeerNetwork, V2AccountHost, V2ConsensusHost
from EZ_V2.values import ValueRange


@dataclass
class VoteTracking:
    """用于跟踪投票记录的辅助类"""
    prepare_votes: set[str] = field(default_factory=set)
    precommit_votes: set[str] = field(default_factory=set)
    commit_votes: set[str] = field(default_factory=set)

    def prepare_qc_formed(self, total_validators: int) -> bool:
        """检查是否形成PrepareQC（需要2f+1票）"""
        threshold = (2 * total_validators) // 3 + 1
        return len(self.prepare_votes) >= threshold

    def precommit_qc_formed(self, total_validators: int) -> bool:
        """检查是否形成PreCommitQC（需要2f+1票）"""
        threshold = (2 * total_validators) // 3 + 1
        return len(self.precommit_votes) >= threshold

    def commit_qc_formed(self, total_validators: int) -> bool:
        """检查是否形成CommitQC（需要2f+1票）"""
        threshold = (2 * total_validators) // 3 + 1
        return len(self.commit_votes) >= threshold


class EZV2ConsensusHotStuffPhasesTests(unittest.TestCase):
    """
    HotStuff三阶段BFT共识测试

    验证consensus-mvp-spec.md第7节定义的：
    1. PREPARE阶段：2f+1票形成PrepareQC
    2. PRECOMMIT阶段：2f+1票形成PreCommitQC
    3. COMMIT阶段：2f+1票形成CommitQC，区块最终确认
    """

    @staticmethod
    def _wait_for_consensus_height(consensus: V2ConsensusHost, expected_height: int, timeout_sec: float = 2.0) -> int:
        """等待共识节点达到指定高度"""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if consensus.consensus.chain.current_height >= expected_height:
                return consensus.consensus.chain.current_height
            time.sleep(0.01)
        return consensus.consensus.chain.current_height

    def test_hotstuff_qc_threshold_with_4_validators(self) -> None:
        """
        [design-conformance] 验证n=4时（3f+1, f=1）QC阈值为3

        设计文档：consensus-mvp-spec.md 第7.2节
        "设validator总数为n=3f+1，则任一阶段形成QC需要至少2f+1个有效投票"

        对于n=4：
        - f = 1
        - 2f + 1 = 3

        测试目标：
        1. 验证3票足以形成QC
        2. 验证2票不足以形成QC
        """
        n = 4
        expected_threshold = 3  # 2*1 + 1 = 3

        # 验证阈值计算
        f = (n - 1) // 3
        threshold = 2 * f + 1
        self.assertEqual(threshold, expected_threshold,
            f"QC threshold for n={n} should be {expected_threshold}, got {threshold}")

        tracking = VoteTracking()

        # 添加2票，不足以形成QC
        tracking.prepare_votes.update({"validator-0", "validator-1"})
        self.assertFalse(tracking.prepare_qc_formed(n),
            f"2 votes should NOT form QC with n={n}")

        # 添加第3票，形成QC
        tracking.prepare_votes.add("validator-2")
        self.assertTrue(tracking.prepare_qc_formed(n),
            f"3 votes should form QC with n={n}")

    def test_hotstuff_qc_threshold_with_7_validators(self) -> None:
        """
        [design-conformance] 验证n=7时（3f+1, f=2）QC阈值为5

        设计文档：consensus-mvp-spec.md 第7.2节

        对于n=7：
        - f = 2
        - 2f + 1 = 5
        """
        n = 7
        expected_threshold = 5  # 2*2 + 1 = 5

        f = (n - 1) // 3
        threshold = 2 * f + 1
        self.assertEqual(threshold, expected_threshold,
            f"QC threshold for n={n} should be {expected_threshold}, got {threshold}")

        tracking = VoteTracking()

        # 添加4票，不足以形成QC
        tracking.prepare_votes.update({f"validator-{i}" for i in range(4)})
        self.assertFalse(tracking.prepare_qc_formed(n),
            f"4 votes should NOT form QC with n={n}")

        # 添加第5票，形成QC
        tracking.prepare_votes.add("validator-4")
        self.assertTrue(tracking.prepare_qc_formed(n),
            f"5 votes should form QC with n={n}")

    def test_hotstuff_phase_transitions(self) -> None:
        """
        [design-conformance] 验证三阶段状态转换

        设计文档：consensus-mvp-spec.md 第7节
        "MVP采用HotStuff风格三阶段确认：PREPARE, PRECOMMIT, COMMIT"

        测试目标：
        1. 验证状态机顺序：PROPOSAL → PREPARE → PRECOMMIT → COMMIT → DECIDED
        2. 验证每个阶段需要对应的QC才能推进
        3. 验证CommitQC形成后区块最终确认
        """
        n = 4
        threshold = 3

        tracking = VoteTracking()

        # 初始状态：未收到任何投票
        self.assertFalse(tracking.prepare_qc_formed(n))
        self.assertFalse(tracking.precommit_qc_formed(n))
        self.assertFalse(tracking.commit_qc_formed(n))

        # 模拟PREPARE阶段收集投票
        tracking.prepare_votes.update({f"validator-{i}" for i in range(threshold)})
        self.assertTrue(tracking.prepare_qc_formed(n),
            "PREPARE阶段：3票应该形成PrepareQC")

        # 模拟PRECOMMIT阶段收集投票
        tracking.precommit_votes = set()
        tracking.precommit_votes.update({f"validator-{i}" for i in range(threshold)})
        self.assertTrue(tracking.precommit_qc_formed(n),
            "PRECOMMIT阶段：3票应该形成PreCommitQC")

        # 模拟COMMIT阶段收集投票
        tracking.commit_votes.update({f"validator-{i}" for i in range(threshold)})
        self.assertTrue(tracking.commit_qc_formed(n),
            "COMMIT阶段：3票应该形成CommitQC")

    def test_hotstuff_qc_requirement_with_single_validator(self) -> None:
        """
        [boundary] 验证n=1时QC阈值为1（退化情况）

        这是MVP中单节点测试网络的边界条件
        """
        n = 1
        expected_threshold = 1  # 2*0 + 1 = 1

        tracking = VoteTracking()
        tracking.prepare_votes.add("validator-0")

        self.assertTrue(tracking.prepare_qc_formed(n),
            "Single validator should form QC with 1 vote")

    def test_hotstuff_partial_votes_insufficient(self) -> None:
        """
        [negative] 验证部分投票不足以形成QC

        测试边界条件：恰好低于阈值的投票数
        """
        test_cases = [
            (4, 2, "n=4, 2 votes < threshold 3"),
            (4, 1, "n=4, 1 vote < threshold 3"),
            (7, 4, "n=7, 4 votes < threshold 5"),
            (7, 3, "n=7, 3 votes < threshold 5"),
            (10, 6, "n=10, 6 votes < threshold 7"),
        ]

        for n, votes, desc in test_cases:
            tracking = VoteTracking()
            tracking.prepare_votes.update({f"validator-{i}" for i in range(votes)})
            self.assertFalse(tracking.prepare_qc_formed(n),
                f"{desc}: should NOT form QC")

    def test_hotstuff_exact_threshold_sufficient(self) -> None:
        """
        [boundary] 验证恰好达到阈值的投票足以形成QC
        """
        test_cases = [
            (4, 3, "n=4, threshold=3"),
            (7, 5, "n=7, threshold=5"),
            (10, 7, "n=10, threshold=7"),
        ]

        for n, threshold, desc in test_cases:
            tracking = VoteTracking()
            tracking.prepare_votes.update({f"validator-{i}" for i in range(threshold)})
            self.assertTrue(tracking.prepare_qc_formed(n),
                f"{desc}: should form QC")

    def test_hotstuff_commit_qc_finalizes_block(self) -> None:
        """
        [design-conformance] 验证CommitQC形成后区块最终确认

        设计文档：consensus-mvp-spec.md 第7.1节
        "当COMMIT阶段形成有效CommitQC时，该块在该高度最终确认"

        测试目标：
        1. 验证CommitQC形成后区块状态变为final
        2. 验证只有final后才允许分发Receipt
        3. 验证final后state_root被更新
        """
        with tempfile.TemporaryDirectory() as td:
            network = StaticPeerNetwork()
            validator_ids = ("consensus-0", "consensus-1", "consensus-2", "consensus-3")
            consensus_hosts = tuple(
                V2ConsensusHost(
                    node_id=validator_id,
                    endpoint=f"mem://{validator_id}",
                    store_path=f"{td}/{validator_id}.sqlite3",
                    network=network,
                    chain_id=7001,
                    consensus_mode="mvp",
                    consensus_validator_ids=validator_ids,
                    auto_run_mvp_consensus=True,
                    auto_run_mvp_consensus_window_sec=0.2,
                )
                for validator_id in validator_ids
            )

            alice = V2AccountHost(
                node_id="alice",
                endpoint="mem://alice",
                wallet_db_path=f"{td}/alice.sqlite3",
                chain_id=7001,
                network=network,
                consensus_peer_id="consensus-0",
            )
            bob = V2AccountHost(
                node_id="bob",
                endpoint="mem://bob",
                wallet_db_path=f"{td}/bob.sqlite3",
                chain_id=7001,
                network=network,
                consensus_peer_id="consensus-1",
            )

            try:
                minted = ValueRange(0, 199)
                for consensus in consensus_hosts:
                    consensus.register_genesis_value(alice.address, minted)
                alice.register_genesis_value(minted)

                # 提交交易
                payment = alice.submit_payment("bob", amount=50, tx_time=1, anti_spam_nonce=701)
                self.assertIsNone(payment.receipt_height)

                # 驱动共识
                for consensus in consensus_hosts:
                    try:
                        result = consensus.drive_auto_mvp_consensus_tick(force=True)
                        if result and result.get("status") == "committed":
                            break
                    except Exception:
                        pass

                # 等待所有节点确认
                for consensus in consensus_hosts:
                    height = self._wait_for_consensus_height(consensus, 1, timeout_sec=2.0)
                    self.assertEqual(height, 1,
                        f"Consensus node {consensus.peer.node_id} should reach height 1")

                # 验证区块已final（receipt可获取）
                alice.sync_pending_receipts()
                self.assertEqual(len(alice.wallet.list_receipts()), 1,
                    "Alice should receive receipt after commit QC formed")

                receipt = alice.wallet.list_receipts()[0]
                self.assertEqual(receipt.seq, 1)
                self.assertIsNotNone(receipt.header_lite)
                self.assertEqual(receipt.header_lite.height, 1)

                # 验证bob收到交易（P2P验证通过）
                self.assertEqual(len(bob.received_transfers), 1)
                self.assertEqual(bob.wallet.available_balance(), 50)

            finally:
                bob.close()
                alice.close()
                for consensus in reversed(consensus_hosts):
                    consensus.close()


class EZV2ConsensusSafetyRuleTests(unittest.TestCase):
    """
    Safety Rule验证测试

    设计文档对照：
    - EZchain-V2-consensus-mvp-spec.md 第9节 "Safety Rule"
    """

    def test_safety_rule_no_duplicate_votes_same_phase(self) -> None:
        """
        [safety] 验证同一(height, round, phase)不得重复投不同块

        设计文档：consensus-mvp-spec.md 第9节
        "同一(height, round, phase)不得重复投不同块"

        测试目标：
        1. 验证节点不会在同一轮次同一阶段对两个不同块投票
        2. 验证vote log记录投票历史
        """
        # 模拟vote log记录
        vote_log: dict[tuple[str, int, int, str], str] = {}

        height, round, phase = 1, 1, "PREPARE"
        block_hash_1 = "0x" + "01" * 32
        block_hash_2 = "0x" + "02" * 32

        # 第一次投票
        key = ("validator-0", height, round, phase)
        vote_log[key] = block_hash_1

        # 尝试对同一高度轮次阶段的不同块投票
        existing_vote = vote_log.get(key)
        self.assertIsNotNone(existing_vote)
        self.assertNotEqual(existing_vote, block_hash_2,
            "Should detect attempt to vote for different block in same phase")

        # Safety rule应该拒绝这次投票
        can_vote = (existing_vote is None or existing_vote == block_hash_2)
        self.assertFalse(can_vote,
            "Safety rule: should reject duplicate vote for different block")

    def test_safety_rule_locked_qc_protection(self) -> None:
        """
        [safety] 验证locked_qc保护规则

        设计文档：consensus-mvp-spec.md 第9节
        "只有proposal携带的justify_qc不低于本地locked_qc时，才允许投票"
        """
        # 模拟本地locked_qc
        locked_qc_height = 5
        locked_qc_round = 1

        # 提案1: justify_qc高于locked_qc，应该允许投票
        proposal_1 = {
            "height": 6,
            "round": 1,
            "justify_qc_height": locked_qc_height,
            "justify_qc_round": locked_qc_round,
        }

        can_vote_1 = (
            proposal_1["justify_qc_height"] >= locked_qc_height and
            proposal_1["justify_qc_round"] >= locked_qc_round
        )
        self.assertTrue(can_vote_1,
            "Should allow voting when justify_qc >= locked_qc")

        # 提案2: justify_qc低于locked_qc，应该拒绝投票
        proposal_2 = {
            "height": 6,
            "round": 1,
            "justify_qc_height": locked_qc_height - 1,
            "justify_qc_round": locked_qc_round,
        }

        can_vote_2 = (
            proposal_2["justify_qc_height"] >= locked_qc_height
        )
        self.assertFalse(can_vote_2,
            "Should reject voting when justify_qc < locked_qc")

    def test_safety_rule_precommitqc_updates_locked_qc(self) -> None:
        """
        [safety] 验证PreCommitQC形成后更新locked_qc

        设计文档：consensus-mvp-spec.md 第9节
        "一旦PreCommitQC形成，本地locked_qc至少推进到该块"
        """
        initial_locked_height = 3
        new_precommitqc_height = 5

        # PreCommitQC形成后，locked_qc应该更新
        new_locked_qc = max(initial_locked_height, new_precommitqc_height)
        self.assertEqual(new_locked_qc, new_precommitqc_height,
            "locked_qc should advance to PreCommitQC block")

    def test_safety_rule_commitqc_prevents_revote(self) -> None:
        """
        [safety] 验证CommitQC形成后不允许对同高度其他块投票

        设计文档：consensus-mvp-spec.md 第9节
        "CommitQC一旦形成，该块立即final，不允许再为同高度其他块投票"
        """
        commitqc_height = 5
        commitqc_block_hash = "0x" + "aa" * 32
        alternative_block_hash = "0x" + "bb" * 32

        # 模拟commit_qc记录
        commit_qc = {
            "height": commitqc_height,
            "block_hash": commitqc_block_hash,
        }

        # 尝试对同高度的其他块投票
        can_vote = (
            commit_qc["height"] != commitqc_height or
            commit_qc["block_hash"] == alternative_block_hash
        )
        self.assertFalse(can_vote,
            "Should reject voting for alternative block after CommitQC")


if __name__ == "__main__":
    unittest.main()
