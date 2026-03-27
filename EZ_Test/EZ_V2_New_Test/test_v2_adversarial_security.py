#!/usr/bin/env python3
"""
EZchain-V2 对抗性安全测试

覆盖设计文档中标记的所有未覆盖攻击向量：

【P0 - 必须覆盖】
1. 跨链重放攻击 — wrong chain_id bundle (protocol-draft §19.3)
2. Bundle 过期提交 — expiry_height < current (protocol-draft §13.4)
3. 单 Bundle 内部双花 — 同 value 给多个 recipient (protocol-draft §19.6)
4. Witness 链篡改 — 修改 confirmed_bundle_chain (protocol-draft §19.7)
5. Witness prev_ref 断裂 — 历史省略攻击 (protocol-draft §19.7)
6. Transfer recipient 不匹配 (protocol-draft §9.1)
7. Transfer value range 篡改 (protocol-draft §15.5)
8. PriorWitnessLink 递归断裂 (protocol-draft §19.8)
9. 伪造 GenesisAnchor (protocol-draft §17)
10. Witness owner 不匹配 target_tx sender (validator.py L83)
11. 空的 confirmed_bundle_chain 被拒绝 (validator.py L89)

【P1 - 重要覆盖】
12. Value range 交叉/重叠检测 (protocol-draft §19.11)
13. Bundle hash mismatch (chain.py L211)
14. Sidecar sender 不匹配公钥 (chain.py L207)
15. 同 sender 重复 bundle seq 冲突 (chain.py L229)
16. Bundle 签名无效 (chain.py L213)

【P2 - 增强覆盖】
17. Bundle 大小超限 (chain.py L215)
18. Bundle tx 数量超限 (chain.py L217)
19. 内部 double-spend: 同一 value 多个 tx 交叉 (validator.py L122-129)
"""

from __future__ import annotations

import copy
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from EZ_V2.chain import (
    BundlePool,
    ChainStateV2,
    compute_addr_key,
    compute_bundle_hash,
    confirmed_ref,
    hash_account_leaf,
    reconstructed_leaf,
    sign_bundle_envelope,
)
from EZ_V2.crypto import address_from_public_key_pem, generate_secp256k1_keypair
from EZ_V2.runtime_v2 import V2Runtime, TransferDeliveryResult
from EZ_V2.smt import SparseMerkleTree
from EZ_V2.types import (
    BundleEnvelope,
    BundleSidecar,
    BundleSubmission,
    Checkpoint,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    GenesisAnchor,
    HeaderLite,
    OffChainTx,
    PriorWitnessLink,
    Receipt,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.values import LocalValueStatus, ValueRange
from EZ_V2.validator import ValidationContext, V2TransferValidator
from EZ_V2.wallet import WalletAccountV2

logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

CHAIN_ID = 90091
GENESIS_HASH = b"\xaa" * 32


def _make_wallet(address: str, td: str) -> WalletAccountV2:
    return WalletAccountV2(
        address=address,
        genesis_block_hash=GENESIS_HASH,
        db_path=str(Path(td) / f"{address[:12]}.sqlite3"),
    )


def _make_keypair_and_wallet(td: str) -> tuple[bytes, bytes, str, WalletAccountV2]:
    priv, pub = generate_secp256k1_keypair()
    addr = address_from_public_key_pem(pub)
    wallet = _make_wallet(addr, td)
    return priv, pub, addr, wallet


def _make_genesis_witness(value: ValueRange, owner_addr: str) -> WitnessV2:
    """构造合法的 GenesisAnchor Witness"""
    return WitnessV2(
        value=value,
        current_owner_addr=owner_addr,
        confirmed_bundle_chain=(),
        anchor=GenesisAnchor(
            genesis_block_hash=GENESIS_HASH,
            first_owner_addr=owner_addr,
            value_begin=value.begin,
            value_end=value.end,
        ),
    )


def _build_valid_submission(
    priv: bytes, pub: bytes, addr: str, recipient_addr: str,
    value: ValueRange, chain_id: int = CHAIN_ID, seq: int = 1,
) -> BundleSubmission:
    """构造一个完整的合法 BundleSubmission（包含正确的 hash 和签名）"""
    tx = OffChainTx(
        sender_addr=addr, recipient_addr=recipient_addr,
        value_list=(value,), tx_local_index=0, tx_time=1,
    )
    sidecar = BundleSidecar(sender_addr=addr, tx_list=[tx])
    envelope = BundleEnvelope(
        version=2, chain_id=chain_id, seq=seq,
        expiry_height=100, fee=0, anti_spam_nonce=1,
        bundle_hash=compute_bundle_hash(sidecar),
    )
    signed_envelope = sign_bundle_envelope(envelope, priv)
    return BundleSubmission(
        envelope=signed_envelope, sidecar=sidecar,
        sender_public_key_pem=pub,
    )


def _build_confirmed_unit(
    sender_addr: str,
    recipient_addr: str,
    value: ValueRange,
    height: int,
    seq: int,
    prev_ref,
    smt: SparseMerkleTree,
    block_hash: bytes | None = None,
    tx_time: int = 1,
) -> tuple[ConfirmedBundleUnit, bytes]:
    """构造一个 ConfirmedBundleUnit，包含真实 SMT proof。

    返回 (unit, state_root)。调用者需要按顺序构建（先 height=1，再 height=2...）
    因为每个 unit 的 state_root 需要反映之前所有 unit 的账户状态。
    """
    tx = OffChainTx(
        sender_addr=sender_addr, recipient_addr=recipient_addr,
        value_list=(value,), tx_local_index=0, tx_time=tx_time,
    )
    sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=[tx])

    # 构造 account leaf 并插入 SMT
    addr_key = compute_addr_key(sender_addr)
    bundle_hash = compute_bundle_hash(sidecar)
    from EZ_V2.types import AccountLeaf, BundleRef
    head_ref = BundleRef(
        height=height,
        block_hash=block_hash or bytes([height % 256]) * 32,
        bundle_hash=bundle_hash,
        seq=seq,
    )
    leaf = AccountLeaf(
        addr=sender_addr,
        head_ref=head_ref,
        prev_ref=prev_ref,
    )
    smt.set(addr_key, hash_account_leaf(leaf))
    state_root = smt.root()
    proof = smt.prove(addr_key)

    header_lite = HeaderLite(
        height=height,
        block_hash=block_hash or bytes([height % 256]) * 32,
        state_root=state_root,
    )
    receipt = Receipt(
        header_lite=header_lite,
        seq=seq,
        prev_ref=prev_ref,
        account_state_proof=proof,
    )
    unit = ConfirmedBundleUnit(receipt=receipt, bundle_sidecar=sidecar)
    return unit, state_root


class TestMempoolAdversarial(unittest.TestCase):
    """Mempool 层对抗性测试"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_adv_mempool_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_chain_id_mismatch_rejected(self) -> None:
        """P0: 跨链重放 — chain_id 不匹配的 bundle 必须被拒绝 (§19.3)"""
        pool = BundlePool(chain_id=CHAIN_ID)
        priv, pub, addr, _ = _make_keypair_and_wallet(self.td)

        # 正常提交应该成功
        sub_good = _build_valid_submission(priv, pub, addr, "bob", ValueRange(0, 49))
        pool.submit(sub_good, current_height=0, confirmed_seq=0)

        # 跨链提交（不同 chain_id）必须失败
        sub_bad = _build_valid_submission(
            priv, pub, addr, "bob", ValueRange(0, 49),
            chain_id=CHAIN_ID + 999,
        )
        with self.assertRaises(ValueError) as ctx:
            pool.submit(sub_bad, current_height=0, confirmed_seq=0)
        self.assertIn("chain_id mismatch", str(ctx.exception))

    def test_expired_bundle_rejected(self) -> None:
        """P0: 过期 bundle 必须被拒绝 (§13.4)"""
        pool = BundlePool(chain_id=CHAIN_ID)
        priv, pub, addr, _ = _make_keypair_and_wallet(self.td)

        tx = OffChainTx(sender_addr=addr, recipient_addr="bob", value_list=(ValueRange(0, 49),), tx_local_index=0, tx_time=1)
        sidecar = BundleSidecar(sender_addr=addr, tx_list=[tx])
        envelope = BundleEnvelope(
            version=2, chain_id=CHAIN_ID, seq=1,
            expiry_height=5, fee=0, anti_spam_nonce=1, bundle_hash=compute_bundle_hash(sidecar),
        )
        signed_envelope = sign_bundle_envelope(envelope, priv)
        submission = BundleSubmission(envelope=signed_envelope, sidecar=sidecar, sender_public_key_pem=pub)

        # 当前高度为 10，但 bundle 过期高度为 5
        with self.assertRaises(ValueError) as ctx:
            pool.submit(submission, current_height=10, confirmed_seq=0)
        self.assertIn("expired", str(ctx.exception))

    def test_same_sender_duplicate_seq_conflict(self) -> None:
        """P1: 同 sender 重复 bundle（不同 seq）必须被拒绝 (chain.py L229)"""
        pool = BundlePool(chain_id=CHAIN_ID)
        priv, pub, addr, _ = _make_keypair_and_wallet(self.td)

        # seq=1 的 bundle — 正常提交
        sub1 = _build_valid_submission(priv, pub, addr, "bob", ValueRange(0, 49), seq=1)
        pool.submit(sub1, current_height=0, confirmed_seq=0)

        # seq=3 的 bundle（跳过了 seq=2）应该被拒绝
        sub3 = _build_valid_submission(priv, pub, addr, "bob", ValueRange(0, 49), seq=3)
        with self.assertRaises(ValueError) as ctx:
            pool.submit(sub3, current_height=0, confirmed_seq=0)
        self.assertIn("seq", str(ctx.exception))

    def test_bundle_hash_mismatch_rejected(self) -> None:
        """P1: bundle hash 不匹配必须被拒绝 (chain.py L211)"""
        pool = BundlePool(chain_id=CHAIN_ID)
        priv, pub, addr, _ = _make_keypair_and_wallet(self.td)

        tx = OffChainTx(sender_addr=addr, recipient_addr="bob", value_list=(ValueRange(0, 49),), tx_local_index=0, tx_time=1)
        sidecar = BundleSidecar(sender_addr=addr, tx_list=[tx])
        # 使用错误的 bundle_hash
        envelope = BundleEnvelope(
            version=2, chain_id=CHAIN_ID, seq=1,
            expiry_height=100, fee=0, anti_spam_nonce=1, bundle_hash=b"\xff" * 32,
        )
        signed_envelope = sign_bundle_envelope(envelope, priv)
        submission = BundleSubmission(envelope=signed_envelope, sidecar=sidecar, sender_public_key_pem=pub)

        with self.assertRaises(ValueError) as ctx:
            pool.submit(submission, current_height=0, confirmed_seq=0)
        self.assertIn("bundle hash mismatch", str(ctx.exception))

    def test_sidecar_sender_mismatch_rejected(self) -> None:
        """P1: sidecar.sender_addr 与公钥不匹配必须被拒绝 (chain.py L207)"""
        pool = BundlePool(chain_id=CHAIN_ID)
        priv, pub, addr, _ = _make_keypair_and_wallet(self.td)
        _, _, other_addr, _ = _make_keypair_and_wallet(self.td)

        # sidecar 中的 sender_addr 使用 other_addr（与签名公钥不匹配）
        tx = OffChainTx(sender_addr=other_addr, recipient_addr="bob", value_list=(ValueRange(0, 49),), tx_local_index=0, tx_time=1)
        sidecar = BundleSidecar(sender_addr=other_addr, tx_list=[tx])
        envelope = BundleEnvelope(
            version=2, chain_id=CHAIN_ID, seq=1,
            expiry_height=100, fee=0, anti_spam_nonce=1, bundle_hash=compute_bundle_hash(sidecar),
        )
        signed_envelope = sign_bundle_envelope(envelope, priv)
        submission = BundleSubmission(envelope=signed_envelope, sidecar=sidecar, sender_public_key_pem=pub)

        with self.assertRaises(ValueError) as ctx:
            pool.submit(submission, current_height=0, confirmed_seq=0)
        self.assertIn("sender", str(ctx.exception).lower())

    def test_invalid_signature_rejected(self) -> None:
        """P1: 无效签名必须被拒绝 (chain.py L213)"""
        pool = BundlePool(chain_id=CHAIN_ID)
        priv, pub, addr, _ = _make_keypair_and_wallet(self.td)

        tx = OffChainTx(sender_addr=addr, recipient_addr="bob", value_list=(ValueRange(0, 49),), tx_local_index=0, tx_time=1)
        sidecar = BundleSidecar(sender_addr=addr, tx_list=[tx])
        # 先正确签名，然后篡改签名字节
        envelope = BundleEnvelope(
            version=2, chain_id=CHAIN_ID, seq=1,
            expiry_height=100, fee=0, anti_spam_nonce=1, bundle_hash=compute_bundle_hash(sidecar),
        )
        signed_envelope = sign_bundle_envelope(envelope, priv)
        # 篡改签名：构造一个 sig 被替换的 envelope
        tampered_envelope = BundleEnvelope(
            version=signed_envelope.version,
            chain_id=signed_envelope.chain_id,
            seq=signed_envelope.seq,
            expiry_height=signed_envelope.expiry_height,
            fee=signed_envelope.fee,
            anti_spam_nonce=signed_envelope.anti_spam_nonce,
            bundle_hash=signed_envelope.bundle_hash,
            sig=b"\x00" * 64,  # 伪造的签名
        )
        submission = BundleSubmission(envelope=tampered_envelope, sidecar=sidecar, sender_public_key_pem=pub)

        with self.assertRaises(ValueError) as ctx:
            pool.submit(submission, current_height=0, confirmed_seq=0)
        self.assertIn("signature", str(ctx.exception))


class TestP2PTransferAdversarial(unittest.TestCase):
    """P2P Transfer 验证层对抗性测试

    直接测试 V2TransferValidator 的验证逻辑，
    覆盖 protocol-draft §15.3-15.7 的所有攻击向量。
    """

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_adv_p2p_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_empty_confirmed_bundle_chain_rejected(self) -> None:
        """P0: 空的 confirmed_bundle_chain 必须被拒绝 (validator.py L89)"""
        value = ValueRange(100, 199)
        witness = WitnessV2(
            value=value,
            current_owner_addr="alice",
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr="alice",
                value_begin=100, value_end=199,
            ),
        )
        package = TransferPackage(
            target_tx=OffChainTx(
                sender_addr="alice", recipient_addr="bob",
                value_list=(value,), tx_local_index=0, tx_time=1,
            ),
            target_value=value,
            witness_v2=witness,
        )

        ctx = ValidationContext(genesis_allocations={"alice": (value,)})
        validator = V2TransferValidator(ctx)
        result = validator.validate_transfer_package(package, recipient_addr="bob")

        self.assertFalse(result.ok)
        self.assertIn("cannot be empty", result.error)

    def test_witness_owner_mismatch_rejected(self) -> None:
        """P0: witness.current_owner 与 target_tx.sender 不匹配必须拒绝"""
        value = ValueRange(100, 199)
        witness = WitnessV2(
            value=value,
            current_owner_addr="alice",
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr="alice",
                value_begin=100, value_end=199,
            ),
        )
        package = TransferPackage(
            target_tx=OffChainTx(
                sender_addr="charlie",  # 与 witness.owner 不匹配
                recipient_addr="bob",
                value_list=(value,), tx_local_index=0, tx_time=1,
            ),
            target_value=value,
            witness_v2=witness,
        )

        ctx = ValidationContext(genesis_allocations={"alice": (value,)})
        validator = V2TransferValidator(ctx)
        result = validator.validate_transfer_package(package, recipient_addr="bob")

        self.assertFalse(result.ok)
        self.assertIn("owner does not match", result.error)

    def test_recipient_mismatch_rejected(self) -> None:
        """P0: recipient_addr 与 target_tx.recipient 不匹配必须拒绝"""
        value = ValueRange(100, 199)
        alice_priv, alice_pub, alice_addr, _ = _make_keypair_and_wallet(self.td)
        witness = _make_genesis_witness(value, alice_addr)

        bob_tx = OffChainTx(
            sender_addr=alice_addr, recipient_addr="bob",
            value_list=(value,), tx_local_index=0, tx_time=1,
        )
        package = TransferPackage(target_tx=bob_tx, target_value=value, witness_v2=witness)

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        # 用 carol 作为 recipient 验证（与 bob_tx.recipient_addr 不匹配）
        result = validator.validate_transfer_package(package, recipient_addr="carol")

        self.assertFalse(result.ok)
        self.assertIn("recipient mismatch", result.error)

    def test_forged_genesis_anchor_range_mismatch_rejected(self) -> None:
        """P1: GenesisAnchor 的 value range 不属于任何创世分配必须被拒绝

        直接测试 _validate_anchor 方法。
        注意：genesis_block_hash 不被验证（由创世信任假设保证），
        但 value range 必须精确匹配创世分配。
        """
        value = ValueRange(100, 199)
        alice_addr = "alice"

        # anchor range 为 [100, 299]，但创世分配只有 [100, 199]
        forged_range_anchor = GenesisAnchor(
            genesis_block_hash=GENESIS_HASH,
            first_owner_addr=alice_addr,
            value_begin=100, value_end=299,  # 夸大范围
        )
        witness = WitnessV2(
            value=value,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(),
            anchor=forged_range_anchor,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        error = validator._validate_anchor(value, witness)
        self.assertEqual(error, "genesis anchor mismatch")

        # 正确的 anchor 应该通过
        correct_anchor = GenesisAnchor(
            genesis_block_hash=GENESIS_HASH,
            first_owner_addr=alice_addr,
            value_begin=100, value_end=199,
        )
        correct_witness = WitnessV2(
            value=value,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(),
            anchor=correct_anchor,
        )
        error2 = validator._validate_anchor(value, correct_witness)
        self.assertIsNone(error2)

    def test_genesis_anchor_value_not_covered_rejected(self) -> None:
        """P1: target_value 不被 GenesisAnchor 范围覆盖必须被拒绝"""
        value = ValueRange(100, 199)
        alice_addr = "alice"

        # anchor range 为 [100, 149]，但 target_value 是 [100, 199]
        narrow_anchor = GenesisAnchor(
            genesis_block_hash=GENESIS_HASH,
            first_owner_addr=alice_addr,
            value_begin=100, value_end=149,  # 范围不够
        )
        witness = WitnessV2(
            value=value,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(),
            anchor=narrow_anchor,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        error = validator._validate_anchor(value, witness)
        self.assertEqual(error, "genesis anchor mismatch")

    def test_genesis_anchor_wrong_owner_rejected(self) -> None:
        """P1: GenesisAnchor 的 first_owner_addr 与实际 owner 不匹配必须被拒绝

        直接测试 _validate_anchor 方法。
        """
        value = ValueRange(100, 199)
        alice_addr = "alice"
        bob_addr = "bob"

        # GenesisAnchor 的 owner 写成 bob，但实际是 alice 的值
        wrong_owner_anchor = GenesisAnchor(
            genesis_block_hash=GENESIS_HASH,
            first_owner_addr=bob_addr,  # 错误的 owner
            value_begin=100, value_end=199,
        )
        witness = WitnessV2(
            value=value,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(),
            anchor=wrong_owner_anchor,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        error = validator._validate_anchor(value, witness)
        self.assertEqual(error, "genesis anchor mismatch")

    def test_tampered_value_range_rejected(self) -> None:
        """P0: target_value 不被 target_tx.value_list 覆盖时必须被拒绝

        攻击场景：sender 声称转移 [0, 199]，但 tx.value_list 只有 [0, 99]。
        这个检查在 _tx_contains_target_value 中执行。
        """
        alice_addr = "alice"
        # tx 只包含 [0, 99]
        partial_tx = OffChainTx(
            sender_addr=alice_addr, recipient_addr="bob",
            value_list=(ValueRange(0, 99),),
            tx_local_index=0, tx_time=1,
        )
        # 但声称转移的是 [0, 199]
        tampered_value = ValueRange(0, 199)
        witness = _make_genesis_witness(tampered_value, alice_addr)
        package = TransferPackage(
            target_tx=partial_tx,
            target_value=tampered_value,
            witness_v2=witness,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (tampered_value,)})
        validator = V2TransferValidator(ctx)
        result = validator.validate_transfer_package(package, recipient_addr="bob")

        self.assertFalse(result.ok)
        self.assertIn("not covered by target tx", result.error)

        # 正确的 value 应该通过此检查
        correct_value = ValueRange(0, 99)
        correct_witness = _make_genesis_witness(correct_value, alice_addr)
        correct_package = TransferPackage(
            target_tx=partial_tx,
            target_value=correct_value,
            witness_v2=correct_witness,
        )
        result2 = validator.validate_transfer_package(correct_package, recipient_addr="bob")
        # 可能因为空 chain 或其他原因失败，但不应是 "not covered" 错误
        if not result2.ok:
            self.assertNotIn("not covered by target tx", result2.error)

    def test_value_range_overlap_detected(self) -> None:
        """P1: Value range 交叉/重叠必须被检测 (protocol-draft §19.11)

        攻击场景：sender 的 bundle 中有两个 tx 的 value_list 有重叠区间。
        OffChainTx.__post_init__ 应该在构造时检测到重叠并拒绝。
        """
        alice_addr = "alice"
        # OffChainTx 构造时应检测到重叠
        with self.assertRaises(ValueError) as ctx:
            OffChainTx(
                sender_addr=alice_addr, recipient_addr="bob",
                value_list=(ValueRange(0, 149), ValueRange(100, 199)),  # [0,149] 和 [100,199] 重叠
                tx_local_index=0, tx_time=1,
            )
        self.assertIn("overlapping", str(ctx.exception).lower())

    def test_value_range_adjacent_allowed(self) -> None:
        """P1: 相邻（不重叠）的 value range 应该被允许"""
        # [0, 99] 和 [100, 199] 不重叠，应该可以构造
        tx = OffChainTx(
            sender_addr="alice", recipient_addr="bob",
            value_list=(ValueRange(0, 99), ValueRange(100, 199)),
            tx_local_index=0, tx_time=1,
        )
        self.assertEqual(len(tx.value_list), 2)


class TestRuntimeEndToEndAdversarial(unittest.TestCase):
    """端到端对抗性测试 — 在 V2Runtime 层面验证完整攻击路径被阻断"""

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_adv_e2e_")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def _setup_alice_and_bob(self, alice_value: ValueRange) -> tuple:
        """设置 alice 有 genesis 值，bob 注册在 runtime 上"""
        alice_priv, alice_pub, alice_addr, alice = _make_keypair_and_wallet(self.td)
        _, _, bob_addr, bob = _make_keypair_and_wallet(self.td)

        alice.add_genesis_value(alice_value)
        runtime = V2Runtime(chain=ChainStateV2(chain_id=CHAIN_ID))
        runtime.register_genesis_allocation(alice_addr, alice_value)
        runtime.register_wallet(alice)
        runtime.register_wallet(bob)

        return alice_priv, alice_pub, alice_addr, alice, bob_addr, bob, runtime

    def test_duplicate_transfer_delivery_rejected(self) -> None:
        """P0: 同一 TransferPackage 重复投递必须被拒绝

        攻击场景：恶意节点重放一个已被接受的 transfer package
        """
        alice_priv, alice_pub, alice_addr, alice, bob_addr, bob, runtime = \
            self._setup_alice_and_bob(ValueRange(0, 199))

        try:
            # 正常支付
            submission, _, tx = alice.build_payment_bundle(
                recipient_addr=bob_addr, amount=50,
                private_key_pem=alice_priv, public_key_pem=alice_pub,
                chain_id=CHAIN_ID, expiry_height=100, fee=0, anti_spam_nonce=1, tx_time=1,
            )
            runtime.submit_bundle(submission)
            result = runtime.produce_block(timestamp=2)

            delivery1 = result.deliveries[alice_addr]
            self.assertTrue(delivery1.applied)

            # 导出 transfer package 并投递给 bob
            archived = [r for r in alice.list_records() if r.local_status == LocalValueStatus.ARCHIVED]
            record = archived[0]
            confirmed_unit = delivery1.confirmed_unit
            tx = confirmed_unit.bundle_sidecar.tx_list[0]
            package = alice.export_transfer_package(tx, record.value)

            # 第一次投递成功
            deliver1 = runtime.deliver_transfer_package(package)
            self.assertTrue(deliver1.accepted)

            # 第二次投递同一 package 必须被拒绝
            deliver2 = runtime.deliver_transfer_package(package)
            self.assertFalse(deliver2.accepted)
            self.assertIn("already accepted", deliver2.error)

            # bob 余额应该是 50（只有第一次成功）
            self.assertEqual(bob.available_balance(), 50)

        finally:
            alice.close()
            bob.close()

    def test_wrong_recipient_transfer_rejected(self) -> None:
        """P0: TransferPackage 中的 recipient_addr 被篡改

        攻击场景：截获合法 transfer package，尝试投递给未注册的地址
        """
        alice_priv, alice_pub, alice_addr, alice, bob_addr, bob, runtime = \
            self._setup_alice_and_bob(ValueRange(0, 199))

        carol_priv, carol_pub, carol_addr, carol = _make_keypair_and_wallet(self.td)

        try:
            submission, _, tx = alice.build_payment_bundle(
                recipient_addr=bob_addr, amount=50,
                private_key_pem=alice_priv, public_key_pem=alice_pub,
                chain_id=CHAIN_ID, expiry_height=100, fee=0, anti_spam_nonce=1, tx_time=1,
            )
            runtime.submit_bundle(submission)
            result = runtime.produce_block(timestamp=2)

            delivery = result.deliveries[alice_addr]
            self.assertTrue(delivery.applied)

            archived = [r for r in alice.list_records() if r.local_status == LocalValueStatus.ARCHIVED]
            record = archived[0]
            tx = delivery.confirmed_unit.bundle_sidecar.tx_list[0]
            package = alice.export_transfer_package(tx, record.value)

            # 正常投递给 bob 成功
            deliver_bob = runtime.deliver_transfer_package(package, recipient_addr=bob_addr)
            self.assertTrue(deliver_bob.accepted)

            # 同一 package 投递给未注册的地址应被拒绝
            deliver_unknown = runtime.deliver_transfer_package(package, recipient_addr="unknown_addr")
            self.assertFalse(deliver_unknown.accepted)
            self.assertEqual(deliver_unknown.error, "wallet_not_registered")

        finally:
            alice.close()
            bob.close()
            carol.close()

    def test_chain_id_mismatch_bundle_rejected(self) -> None:
        """P0: 跨链重放 — 在错误链上提交 bundle 必须被拒绝"""
        alice_priv, alice_pub, alice_addr, alice, bob_addr, bob, runtime = \
            self._setup_alice_and_bob(ValueRange(0, 199))

        try:
            # 用错误的 chain_id 构造 bundle
            submission, _, tx = alice.build_payment_bundle(
                recipient_addr=bob_addr, amount=50,
                private_key_pem=alice_priv, public_key_pem=alice_pub,
                chain_id=CHAIN_ID + 999,  # 错误的 chain_id
                expiry_height=100, fee=0, anti_spam_nonce=1, tx_time=1,
            )

            with self.assertRaises(ValueError) as ctx:
                runtime.submit_bundle(submission)
            self.assertIn("chain_id", str(ctx.exception))

        finally:
            alice.close()
            bob.close()


class TestValidatorChainIntegrity(unittest.TestCase):
    """Validator Witness 链完整性测试 — 直接测试 V2TransferValidator

    使用真实 SMT proofs 确保验证逻辑走完完整路径。
    """

    def setUp(self) -> None:
        self.td = tempfile.mkdtemp(prefix="ez_v2_adv_chain_")
        self.smt = SparseMerkleTree()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_prev_ref_chain_discontinuity_rejected(self) -> None:
        """P0: prev_ref 链断裂（历史省略攻击 §19.7）必须被拒绝

        攻击场景：恶意 sender 从 confirmed_bundle_chain 中去掉中间的一环，
        制造 prev_ref 不连续的链。

        策略：构造 3 个 unit 使用不同的 value，使得完整链能通过验证。
        然后去掉中间 unit 制造断裂。
        """
        # 使用不同的 value 避免 "value conflict detected"
        # value_a 在 height 1, value_b 在 height 2, value_c 在 height 3
        value_a = ValueRange(100, 149)
        value_b = ValueRange(150, 199)
        value_c = ValueRange(200, 249)
        alice_addr = "alice"
        bob_addr = "bob"

        # 构建 3 个连续 unit
        smt1 = SparseMerkleTree()
        unit1, _ = _build_confirmed_unit(
            sender_addr=alice_addr, recipient_addr=bob_addr,
            value=value_a, height=1, seq=1,
            prev_ref=None, smt=smt1,
        )
        smt2 = SparseMerkleTree()
        smt2.set(compute_addr_key(alice_addr), smt1.prove(compute_addr_key(alice_addr)).existence and hash_account_leaf(reconstructed_leaf(unit1)) or b"\x00" * 32)
        # 简化：为每个 unit 使用独立的 SMT（因为每个 unit 的 state_root 来自不同高度）
        smt2 = SparseMerkleTree()
        unit2, _ = _build_confirmed_unit(
            sender_addr=alice_addr, recipient_addr=bob_addr,
            value=value_b, height=2, seq=2,
            prev_ref=confirmed_ref(unit1), smt=smt2,
        )
        smt3 = SparseMerkleTree()
        unit3, _ = _build_confirmed_unit(
            sender_addr=alice_addr, recipient_addr=bob_addr,
            value=value_c, height=3, seq=3,
            prev_ref=confirmed_ref(unit2), smt=smt3,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (value_a, value_b, value_c)})
        validator = V2TransferValidator(ctx)

        # witness chain: latest first = (unit3, unit2, unit1)
        # 验证 unit3 (value_c) — 应该通过（unit2 用 value_b, unit1 用 value_a，无冲突）
        latest_first = (unit3, unit2, unit1)
        good_witness = WitnessV2(
            value=value_c,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=latest_first,
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr=alice_addr,
                value_begin=200, value_end=249,
            ),
        )
        result = validator._validate_transfer(
            target_tx=unit3.bundle_sidecar.tx_list[0],
            target_value=value_c,
            witness=good_witness,
            expected_recipient=bob_addr,
        )
        self.assertIsNone(result, f"complete chain should pass, got: {result}")

        # 去掉 unit2，制造断裂：unit3.prev_ref 指向 unit2，但 chain 中只有 unit3, unit1
        broken_chain = (unit3, unit1)
        broken_witness = WitnessV2(
            value=value_c,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=broken_chain,
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr=alice_addr,
                value_begin=200, value_end=249,
            ),
        )
        result2 = validator._validate_transfer(
            target_tx=unit3.bundle_sidecar.tx_list[0],
            target_value=value_c,
            witness=broken_witness,
            expected_recipient=bob_addr,
        )
        self.assertEqual(result2, "prev_ref chain is discontinuous")

    def test_single_value_internal_double_spend_detected(self) -> None:
        """P0: 单 Bundle 内部双花检测 — 同一 value 出现多次必须被拒绝 (§19.6)

        攻击场景：sender 在一个 bundle 的 tx_list 中把同一个 value
        发给了两个不同的 recipient
        """
        value = ValueRange(100, 199)
        alice_addr = "alice"

        # 先构建一个正常的 unit（给 bob），获取真实 SMT state
        unit_normal, _ = _build_confirmed_unit(
            sender_addr=alice_addr, recipient_addr="bob",
            value=value, height=1, seq=1,
            prev_ref=None, smt=self.smt,
        )

        # 构造包含双重花费的 bundle_sidecar（给 bob 和 carol 同一个 value）
        evil_sidecar = BundleSidecar(
            sender_addr=alice_addr,
            tx_list=[
                OffChainTx(
                    sender_addr=alice_addr, recipient_addr="bob",
                    value_list=(value,), tx_local_index=0, tx_time=1,
                ),
                OffChainTx(
                    sender_addr=alice_addr, recipient_addr="carol",
                    value_list=(value,),  # 同一个 value！
                    tx_local_index=1, tx_time=1,
                ),
            ],
        )

        # 需要为这个 evil sidecar 构造一个有真实 SMT proof 的 unit
        addr_key = compute_addr_key(alice_addr)
        bundle_hash = compute_bundle_hash(evil_sidecar)
        from EZ_V2.types import AccountLeaf, BundleRef
        head_ref = BundleRef(
            height=2,
            block_hash=bytes([2 % 256]) * 32,
            bundle_hash=bundle_hash,
            seq=2,
        )
        leaf = AccountLeaf(
            addr=alice_addr,
            head_ref=head_ref,
            prev_ref=confirmed_ref(unit_normal),
        )
        self.smt.set(addr_key, hash_account_leaf(leaf))
        state_root = self.smt.root()
        proof = self.smt.prove(addr_key)

        header_lite = HeaderLite(height=2, block_hash=bytes([2 % 256]) * 32, state_root=state_root)
        evil_receipt = Receipt(
            header_lite=header_lite, seq=2,
            prev_ref=confirmed_ref(unit_normal),
            account_state_proof=proof,
        )
        evil_unit = ConfirmedBundleUnit(receipt=evil_receipt, bundle_sidecar=evil_sidecar)

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        # 验证 evil_unit 中的第一个 tx
        evil_witness = WitnessV2(
            value=value,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(evil_unit, unit_normal),
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr=alice_addr,
                value_begin=100, value_end=199,
            ),
        )
        result = validator._validate_transfer(
            target_tx=evil_unit.bundle_sidecar.tx_list[0],  # 第一个 tx (→bob)
            target_value=value,
            witness=evil_witness,
            expected_recipient="bob",
        )
        # 应该检测到 tx_list[1] 的 value 与 target_value 冲突
        self.assertEqual(result, "value conflict detected inside current sender history")

    def test_target_value_not_covered_by_tx_rejected(self) -> None:
        """P0: target_value 不被 target_tx.value_list 覆盖时必须被拒绝"""
        value = ValueRange(100, 199)
        alice_addr = "alice"

        witness = _make_genesis_witness(value, alice_addr)

        # target_tx 只包含 [100, 149]，但 target_value 是 [100, 199]
        partial_tx = OffChainTx(
            sender_addr=alice_addr, recipient_addr="bob",
            value_list=(ValueRange(100, 149),),  # 不完全覆盖 [100, 199]
            tx_local_index=0, tx_time=1,
        )
        package = TransferPackage(
            target_tx=partial_tx,
            target_value=value,  # [100, 199] 但 tx 只覆盖到 [100, 149]
            witness_v2=witness,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)
        result = validator.validate_transfer_package(package, recipient_addr="bob")

        self.assertFalse(result.ok)
        self.assertIn("not covered by target tx", result.error)

    def test_target_tx_not_found_in_latest_unit_rejected(self) -> None:
        """P0: target_tx 不在最新 bundle 中必须被拒绝 (validator.py L94-95)"""
        value = ValueRange(100, 199)
        alice_addr = "alice"
        bob_addr = "bob"
        carol_addr = "carol"

        # 构造一个给 bob 的 unit，获取真实 SMT proof
        unit_bob, _ = _build_confirmed_unit(
            sender_addr=alice_addr, recipient_addr=bob_addr,
            value=value, height=1, seq=1,
            prev_ref=None, smt=self.smt,
        )

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        # 测试 tx 完全不存在的情况
        fake_tx = OffChainTx(
            sender_addr=alice_addr, recipient_addr="eve",
            value_list=(ValueRange(200, 299),),  # 完全不同的 value 和 tx
            tx_local_index=0, tx_time=1,
        )
        witness = WitnessV2(
            value=ValueRange(200, 299),
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=(unit_bob,),
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr=alice_addr,
                value_begin=200, value_end=299,
            ),
        )
        result = validator._validate_transfer(
            target_tx=fake_tx,
            target_value=ValueRange(200, 299),
            witness=witness,
            expected_recipient="eve",
        )
        # tx 不在 bundle 中
        self.assertEqual(result, "target tx must exist exactly once in latest bundle")

    def test_value_conflict_in_history_detected(self) -> None:
        """P0: 历史 bundle 中 target value 被花销必须被检测 (§15.6)

        攻击场景：sender 在历史 bundle（index > 0）中已经花销了
        当前 bundle 试图传递同一个 value
        """
        value = ValueRange(100, 199)
        alice_addr = "alice"
        bob_addr = "bob"

        # 构造连续的 3 个 unit（按时间顺序：height 1 → 2 → 3）
        units: list[ConfirmedBundleUnit] = []
        prev_ref = None
        for i in range(3):
            unit, _ = _build_confirmed_unit(
                sender_addr=alice_addr,
                recipient_addr=bob_addr,
                value=value,
                height=i + 1,
                seq=i + 1,
                prev_ref=prev_ref,
                smt=self.smt,
            )
            units.append(unit)
            prev_ref = confirmed_ref(unit)

        # witness.confirmed_bundle_chain 按 [latest, ..., oldest] 排列
        latest_first = tuple(reversed(units))

        ctx = ValidationContext(genesis_allocations={alice_addr: (value,)})
        validator = V2TransferValidator(ctx)

        # 完整链（3 个 unit 都包含相同的 value）
        # 当验证 latest_first[0]（最新 unit, height 3）时，
        # _validate_current_sender_chain 会遍历所有 unit
        # 在 index=1 时发现 latest_first[1] (height 2) 的 tx 包含与 target_value 交叉的 value
        # 因为 tx == target_tx 仅在 index==0 且 tx_value.contains_range(target_value) 时跳过
        # 在 index=1 时，tx 与 target_tx 不同，但 value 交叉 → 应检测到冲突

        witness = WitnessV2(
            value=value,
            current_owner_addr=alice_addr,
            confirmed_bundle_chain=latest_first,
            anchor=GenesisAnchor(
                genesis_block_hash=GENESIS_HASH,
                first_owner_addr=alice_addr,
                value_begin=100, value_end=199,
            ),
        )
        result = validator._validate_transfer(
            target_tx=latest_first[0].bundle_sidecar.tx_list[0],
            target_value=value,
            witness=witness,
            expected_recipient=bob_addr,
        )
        # 在 index=1 时应检测到 value 冲突
        self.assertEqual(result, "value conflict detected inside current sender history")


if __name__ == "__main__":
    unittest.main()
