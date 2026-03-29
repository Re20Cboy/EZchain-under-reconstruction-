"""
EZchain-V2 链核心测试

设计文档对照：
- EZchain-V2-protocol-draft.md 第9-11节：bundle pool、block build、receipt/ref绑定
- EZchain-V2-small-scale-simulation.md：mempool快照与区块构建

测试类别：
- design-conformance: 验证bundle pool、block build符合设计
- invariants: 验证ref链、receipt绑定正确性
- negative: 验证非法提交被拒绝
- boundary: 验证边界条件
"""

from __future__ import annotations

import unittest

from EZ_V2.chain import (
    BundlePool,
    ChainStateV2,
    ReceiptCache,
    compute_addr_key,
    compute_bundle_hash,
    compute_bundle_sighash,
    confirmed_ref,
    hash_account_leaf,
    merkle_root,
    sign_bundle_envelope,
    verify_bundle_envelope,
)
from EZ_V2.crypto import (
    address_from_public_key_pem,
    generate_secp256k1_keypair,
    keccak256,
)
from EZ_V2.types import (
    AccountLeaf,
    BundleEnvelope,
    BundleRef,
    BundleSidecar,
    BundleSubmission,
    OffChainTx,
    Receipt,
    HeaderLite,
)
from EZ_V2.values import ValueRange


class EZV2MerkleRootTests(unittest.TestCase):
    """
    [design-conformance] Merkle根计算测试
    """

    def test_merkle_root_with_single_leaf(self) -> None:
        """验证单叶子Merkle根计算"""
        leaf = b"\x01" * 32
        root = merkle_root([leaf])
        # 单叶子直接返回叶子本身（不需要再hash）
        self.assertEqual(root, leaf)

    def test_merkle_root_with_two_leaves(self) -> None:
        """验证两叶子Merkle根计算"""
        leaf1 = b"\x01" * 32
        leaf2 = b"\x02" * 32
        root = merkle_root([leaf1, leaf2])
        expected = keccak256(b"EZCHAIN_MERKLE_NODE_V2" + leaf1 + leaf2)
        self.assertEqual(root, expected)

    def test_merkle_root_with_empty_list(self) -> None:
        """验证空列表返回特殊空根"""
        from EZ_V2.chain import MERKLE_EMPTY

        root = merkle_root([])
        self.assertEqual(root, MERKLE_EMPTY)

    def test_merkle_root_with_odd_leaves(self) -> None:
        """验证奇数个叶子时最后一个被复制"""
        leaf1 = b"\x01" * 32
        leaf2 = b"\x02" * 32
        leaf3 = b"\x03" * 32

        root = merkle_root([leaf1, leaf2, leaf3])
        # leaf3应该被复制
        expected_parent = keccak256(b"EZCHAIN_MERKLE_NODE_V2" + leaf3 + leaf3)
        expected_left = keccak256(b"EZCHAIN_MERKLE_NODE_V2" + leaf1 + leaf2)
        expected = keccak256(b"EZCHAIN_MERKLE_NODE_V2" + expected_left + expected_parent)
        self.assertEqual(root, expected)


class EZV2BundleHashTests(unittest.TestCase):
    """
    [design-conformance] Bundle哈希计算测试
    """

    def test_compute_bundle_hash_deterministic(self) -> None:
        """验证bundle哈希计算是确定性的"""
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))

        hash1 = compute_bundle_hash(sidecar)
        hash2 = compute_bundle_hash(sidecar)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 32)

    def test_compute_bundle_hash_includes_all_tx_fields(self) -> None:
        """验证bundle哈希包含所有交易字段"""
        tx1 = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        tx2 = OffChainTx("alice", "bob", (ValueRange(50, 99),), 1, 1)

        sidecar1 = BundleSidecar(sender_addr="alice", tx_list=(tx1,))
        sidecar2 = BundleSidecar(sender_addr="alice", tx_list=(tx1, tx2))

        hash1 = compute_bundle_hash(sidecar1)
        hash2 = compute_bundle_hash(sidecar2)

        self.assertNotEqual(hash1, hash2)


class EZV2BundleSignatureTests(unittest.TestCase):
    """
    [design-conformance] Bundle签名测试
    """

    def test_sign_and_verify_bundle(self) -> None:
        """验证签名和验证流程正确"""
        priv, pub = generate_secp256k1_keypair()

        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )

        signed = sign_bundle_envelope(envelope, priv)
        self.assertTrue(verify_bundle_envelope(signed, pub))
        self.assertNotEqual(signed.sig, b"")

    def test_verify_rejects_tampered_envelope(self) -> None:
        """验证拒绝被篡改的envelope"""
        priv, pub = generate_secp256k1_keypair()

        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )

        signed = sign_bundle_envelope(envelope, priv)

        # 篡改envelope
        from dataclasses import replace
        tampered = replace(signed, fee=999)

        self.assertFalse(verify_bundle_envelope(tampered, pub))

    def test_verify_returns_false_for_unsigned_envelope(self) -> None:
        """验证未签名envelope验证失败"""
        _, pub = generate_secp256k1_keypair()

        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )

        self.assertFalse(verify_bundle_envelope(envelope, pub))

    def test_sighash_includes_all_envelope_fields(self) -> None:
        """验证sighash包含所有envelope字段"""
        envelope1 = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )

        envelope2 = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=2,  # 不同的fee
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )

        sighash1 = compute_bundle_sighash(envelope1)
        sighash2 = compute_bundle_sighash(envelope2)

        self.assertNotEqual(sighash1, sighash2)


class EZV2BundlePoolTests(unittest.TestCase):
    """
    [design-conformance] BundlePool测试
    """

    def _make_submission(
        self,
        sender_addr: str = "alice",
        seq: int = 1,
        chain_id: int = 7001,
        fee: int = 1,
        expiry_height: int = 100,
    ) -> tuple[BundleSubmission, bytes, bytes]:
        """辅助方法：创建BundleSubmission"""
        priv, pub = generate_secp256k1_keypair()
        actual_addr = address_from_public_key_pem(pub)

        if sender_addr != "alice":
            # 使用指定sender
            priv, pub = generate_secp256k1_keypair()
            actual_addr = address_from_public_key_pem(pub)

        tx = OffChainTx(
            actual_addr,
            "bob",
            (ValueRange(0, 49),),
            0,
            1,
        )
        sidecar = BundleSidecar(sender_addr=actual_addr, tx_list=(tx,))
        envelope = BundleEnvelope(
            version=1,
            chain_id=chain_id,
            seq=seq,
            expiry_height=expiry_height,
            fee=fee,
            anti_spam_nonce=123,
            bundle_hash=compute_bundle_hash(sidecar),
        )
        signed = sign_bundle_envelope(envelope, priv)

        submission = BundleSubmission(
            envelope=signed,
            sidecar=sidecar,
            sender_public_key_pem=pub,
        )
        return submission, priv, pub

    def test_bundle_pool_accepts_valid_submission(self) -> None:
        """验证BundlePool接受有效提交"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission()

        sender = pool.submit(submission, current_height=1, confirmed_seq=0)
        self.assertEqual(sender, address_from_public_key_pem(submission.sender_public_key_pem))

    def test_bundle_pool_rejects_chain_id_mismatch(self) -> None:
        """验证BundlePool拒绝chain_id不匹配"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission(chain_id=9999)

        with self.assertRaises(ValueError):
            pool.submit(submission, current_height=1, confirmed_seq=0)

    def test_bundle_pool_rejects_expired_bundle(self) -> None:
        """验证BundlePool拒绝过期bundle"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission()

        with self.assertRaises(ValueError):
            pool.submit(submission, current_height=101, confirmed_seq=0)  # expiry_height=100

    def test_bundle_pool_rejects_hash_mismatch(self) -> None:
        """验证BundlePool拒绝hash不匹配"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission()

        # 篡改bundle_hash
        from dataclasses import replace
        tampered = replace(
            submission,
            envelope=replace(submission.envelope, bundle_hash=b"\xFF" * 32),
        )

        with self.assertRaises(ValueError):
            pool.submit(tampered, current_height=1, confirmed_seq=0)

    def test_bundle_pool_rejects_invalid_signature(self) -> None:
        """验证BundlePool拒绝无效签名"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission()

        # 篡改签名
        from dataclasses import replace
        tampered = replace(
            submission,
            envelope=replace(submission.envelope, sig=b"\x00" * 64),
        )

        with self.assertRaises(ValueError):
            pool.submit(tampered, current_height=1, confirmed_seq=0)

    def test_bundle_pool_rejects_wrong_seq(self) -> None:
        """验证BundlePool拒绝错误的seq"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission(seq=5)

        with self.assertRaises(ValueError):
            pool.submit(submission, current_height=1, confirmed_seq=0)  # expected_seq=1

    def test_bundle_pool_allows_replacement_with_higher_fee(self) -> None:
        """验证BundlePool允许更高fee替换"""
        pool = BundlePool(chain_id=7001)
        submission1, priv1, pub1 = self._make_submission(fee=1)

        pool.submit(submission1, current_height=1, confirmed_seq=0)

        # 更高fee的替换（使用相同sender）
        from dataclasses import replace
        tx = OffChainTx(
            address_from_public_key_pem(pub1),
            "bob",
            (ValueRange(0, 49),),
            0,
            1,
        )
        sidecar = BundleSidecar(sender_addr=address_from_public_key_pem(pub1), tx_list=(tx,))
        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=2,  # 更高fee
            anti_spam_nonce=124,  # 不同nonce避免重复bundle_hash
            bundle_hash=compute_bundle_hash(sidecar),
        )
        signed = sign_bundle_envelope(envelope, priv1)

        submission2 = BundleSubmission(
            envelope=signed,
            sidecar=sidecar,
            sender_public_key_pem=pub1,
        )

        sender = pool.submit(submission2, current_height=1, confirmed_seq=0)
        self.assertEqual(sender, address_from_public_key_pem(pub1))

    def test_bundle_pool_rejects_replacement_with_lower_fee(self) -> None:
        """验证BundlePool拒绝更低fee替换"""
        pool = BundlePool(chain_id=7001)
        submission1, priv1, pub1 = self._make_submission(fee=2)

        pool.submit(submission1, current_height=1, confirmed_seq=0)

        # 更低fee的替换（使用相同sender）
        tx = OffChainTx(
            address_from_public_key_pem(pub1),
            "bob",
            (ValueRange(0, 49),),
            0,
            1,
        )
        sidecar = BundleSidecar(sender_addr=address_from_public_key_pem(pub1), tx_list=(tx,))
        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,  # 更低fee
            anti_spam_nonce=125,  # 不同nonce
            bundle_hash=compute_bundle_hash(sidecar),
        )
        signed = sign_bundle_envelope(envelope, priv1)

        submission2 = BundleSubmission(
            envelope=signed,
            sidecar=sidecar,
            sender_public_key_pem=pub1,
        )

        with self.assertRaises(ValueError):
            pool.submit(submission2, current_height=1, confirmed_seq=0)

    def test_bundle_pool_rejects_conflicting_same_seq_even_with_higher_fee(self) -> None:
        """验证不同sidecar不能仅靠更高fee覆盖现有pending bundle"""
        pool = BundlePool(chain_id=7001)
        submission1, priv1, pub1 = self._make_submission(fee=1)

        pool.submit(submission1, current_height=1, confirmed_seq=0)

        tx = OffChainTx(
            address_from_public_key_pem(pub1),
            "carol",
            (ValueRange(0, 49),),
            0,
            1,
        )
        sidecar = BundleSidecar(sender_addr=address_from_public_key_pem(pub1), tx_list=(tx,))
        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=2,
            anti_spam_nonce=126,
            bundle_hash=compute_bundle_hash(sidecar),
        )
        signed = sign_bundle_envelope(envelope, priv1)

        submission2 = BundleSubmission(
            envelope=signed,
            sidecar=sidecar,
            sender_public_key_pem=pub1,
        )

        with self.assertRaisesRegex(ValueError, "sender already has a different pending bundle"):
            pool.submit(submission2, current_height=1, confirmed_seq=0)

    def test_bundle_pool_rejects_old_fee_replay_after_same_bundle_fee_bump(self) -> None:
        """验证同bundle_hash被更高fee替换后，旧fee重放不会把pending降级"""
        pool = BundlePool(chain_id=7001)
        submission1, priv1, pub1 = self._make_submission(fee=0)

        pool.submit(submission1, current_height=1, confirmed_seq=0)

        bumped_envelope = BundleEnvelope(
            version=submission1.envelope.version,
            chain_id=submission1.envelope.chain_id,
            seq=submission1.envelope.seq,
            expiry_height=submission1.envelope.expiry_height,
            fee=2,
            anti_spam_nonce=submission1.envelope.anti_spam_nonce + 1,
            bundle_hash=submission1.envelope.bundle_hash,
        )
        bumped_submission = BundleSubmission(
            envelope=sign_bundle_envelope(bumped_envelope, priv1),
            sidecar=submission1.sidecar,
            sender_public_key_pem=pub1,
        )

        pool.submit(bumped_submission, current_height=1, confirmed_seq=0)

        with self.assertRaisesRegex(ValueError, "replacement bundle fee too low"):
            pool.submit(submission1, current_height=1, confirmed_seq=0)

        snapshot = pool.snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0].envelope.bundle_hash, submission1.envelope.bundle_hash)
        self.assertEqual(snapshot[0].envelope.fee, 2)

    def test_bundle_pool_accepts_identical_replay_idempotently(self) -> None:
        """验证同一submission的完全重复重投不会污染pending状态"""
        pool = BundlePool(chain_id=7001)
        submission, _, _ = self._make_submission(fee=0)

        first_sender = pool.submit(submission, current_height=1, confirmed_seq=0)
        second_sender = pool.submit(submission, current_height=1, confirmed_seq=0)

        snapshot = pool.snapshot()
        self.assertEqual(first_sender, second_sender)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0], submission)

    def test_bundle_pool_snapshot_returns_ordered_by_addr_key(self) -> None:
        """验证snapshot按addr_key排序"""
        pool = BundlePool(chain_id=7001)

        # 提交多个bundle（不同sender）
        for i in range(3):
            submission, _, _ = self._make_submission()
            pool.submit(submission, current_height=1, confirmed_seq=0)

        snapshot = pool.snapshot()

        # 验证已按addr_key排序
        addr_keys = [compute_addr_key(s.sidecar.sender_addr) for s in snapshot]
        self.assertEqual(addr_keys, sorted(addr_keys))


class EZV2ReceiptCacheTests(unittest.TestCase):
    """
    [design-conformance] ReceiptCache测试
    """

    def test_receipt_cache_add_and_retrieve_by_addr_seq(self) -> None:
        """验证ReceiptCache能按地址和seq存储和检索"""
        cache = ReceiptCache(max_blocks=32)

        from EZ_V2.types import SparseMerkleProof
        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        ref = BundleRef(height=1, block_hash=b"\x11" * 32, bundle_hash=b"\x33" * 32, seq=1)

        cache.add("alice", receipt, ref)

        response = cache.get_receipt("alice", 1)
        self.assertEqual(response.status, "ok")
        self.assertIsNotNone(response.receipt)
        self.assertEqual(response.receipt.seq, 1)

    def test_receipt_cache_add_and_retrieve_by_ref(self) -> None:
        """验证ReceiptCache能按ref检索"""
        cache = ReceiptCache(max_blocks=32)

        from EZ_V2.types import SparseMerkleProof
        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        ref = BundleRef(height=1, block_hash=b"\x11" * 32, bundle_hash=b"\x33" * 32, seq=1)

        cache.add("alice", receipt, ref)

        response = cache.get_receipt_by_ref(ref)
        self.assertEqual(response.status, "ok")
        self.assertIsNotNone(response.receipt)

    def test_receipt_cache_returns_missing_for_unknown(self) -> None:
        """验证ReceiptCache对未知receipt返回missing"""
        cache = ReceiptCache(max_blocks=32)

        response = cache.get_receipt("alice", 1)
        self.assertEqual(response.status, "missing")
        self.assertIsNone(response.receipt)


class EZV2ConfirmedRefTests(unittest.TestCase):
    """
    [invariants] confirmed_ref绑定测试

    设计文档：protocol-draft.md 第8节
    验证confirmed_ref正确绑定receipt和bundle信息
    """

    def test_confirmed_ref_creates_bundle_ref_from_unit(self) -> None:
        """验证confirmed_ref从ConfirmedBundleUnit创建BundleRef"""
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))
        bundle_h = compute_bundle_hash(sidecar)

        from EZ_V2.types import SparseMerkleProof, ConfirmedBundleUnit
        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )

        unit = ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)

        ref = confirmed_ref(unit)

        self.assertEqual(ref.height, 1)
        self.assertEqual(ref.block_hash, b"\x11" * 32)
        self.assertEqual(ref.bundle_hash, bundle_h)
        self.assertEqual(ref.seq, 1)


class EZV2AccountLeafTests(unittest.TestCase):
    """
    [design-conformance] AccountLeaf测试
    """

    def test_hash_account_leaf_is_deterministic(self) -> None:
        """验证AccountLeaf哈希是确定性的"""
        ref = BundleRef(height=1, block_hash=b"\x11" * 32, bundle_hash=b"\x22" * 32, seq=1)
        leaf = AccountLeaf(addr="alice", head_ref=ref, prev_ref=None)

        hash1 = hash_account_leaf(leaf)
        hash2 = hash_account_leaf(leaf)

        self.assertEqual(hash1, hash2)

    def test_hash_account_leaf_includes_all_fields(self) -> None:
        """验证AccountLeaf哈希包含所有字段"""
        ref1 = BundleRef(height=1, block_hash=b"\x11" * 32, bundle_hash=b"\x22" * 32, seq=1)
        ref2 = BundleRef(height=1, block_hash=b"\x11" * 32, bundle_hash=b"\x22" * 32, seq=1)

        leaf1 = AccountLeaf(addr="alice", head_ref=ref1, prev_ref=None)
        leaf2 = AccountLeaf(addr="alice", head_ref=ref2, prev_ref=ref2)  # 有prev_ref

        hash1 = hash_account_leaf(leaf1)
        hash2 = hash_account_leaf(leaf2)

        self.assertNotEqual(hash1, hash2)


class EZV2ChainStateTests(unittest.TestCase):
    """
    [design-conformance] ChainStateV2测试
    """

    def test_chain_state_initialization(self) -> None:
        """验证ChainStateV2正确初始化"""
        chain = ChainStateV2(chain_id=7001)

        self.assertEqual(chain.chain_id, 7001)
        self.assertEqual(chain.current_height, 0)
        self.assertIsNotNone(chain.tree)
        self.assertIsNotNone(chain.bundle_pool)
        self.assertIsNotNone(chain.receipt_cache)

    def test_chain_state_copy_creates_independent_copy(self) -> None:
        """验证copy创建独立副本"""
        chain = ChainStateV2(chain_id=7001)

        copy = chain.copy()

        self.assertEqual(copy.chain_id, chain.chain_id)
        self.assertEqual(copy.current_height, chain.current_height)

        # 验证是独立对象
        self.assertIsNot(copy, chain)
        self.assertIsNot(copy.tree, chain.tree)

    def test_apply_block_rejects_bundle_expired_at_block_height(self) -> None:
        """验证follower不会接受被恶意proposer塞入区块的过期bundle"""
        proposer = ChainStateV2(chain_id=7001)
        submission, _, _ = EZV2BundlePoolTests()._make_submission(expiry_height=0)

        block, _ = proposer._execute_submissions(
            submissions=[submission],
            timestamp=1,
            proposer_sig=b"",
            consensus_extra=b"",
            remove_from_pool=False,
        )

        follower = ChainStateV2(chain_id=7001)
        with self.assertRaisesRegex(ValueError, "bundle expired"):
            follower.apply_block(block)


if __name__ == "__main__":
    unittest.main()
