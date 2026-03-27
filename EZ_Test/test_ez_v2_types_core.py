"""
EZchain-V2 协议类型核心测试

设计文档对照：
- EZchain-V2-protocol-draft.md 第6-8节：协议对象定义
- EZchain-V2 desgin-human-write.md：核心设计理念

测试类别：
- design-conformance: 验证协议对象构造符合设计
- negative: 验证篡改、重放、签名错误被正确拒绝
- boundary: 验证边界条件处理
- serialization: 验证序列化/反序列化正确性
"""

from __future__ import annotations

import unittest

from EZ_V2.types import (
    AccountLeaf,
    BundleEnvelope,
    BundleRef,
    BundleSidecar,
    OffChainTx,
    PendingBundleContext,
)


class EZV2TypesConstructionTests(unittest.TestCase):
    """
    [design-conformance] 协议对象构造测试

    验证协议对象能够正确构造，且符合设计定义的约束
    """

    def test_bundle_ref_construction_with_valid_fields(self) -> None:
        """验证BundleRef能用有效字段构造"""
        ref = BundleRef(
            height=1,
            block_hash=b"\x11" * 32,
            bundle_hash=b"\x22" * 32,
            seq=1,
        )
        self.assertEqual(ref.height, 1)
        self.assertEqual(ref.seq, 1)

    def test_off_chain_tx_construction_with_sorted_values(self) -> None:
        """验证OffChainTx构造要求value_list已排序"""
        from EZ_V2.values import ValueRange

        tx = OffChainTx(
            sender_addr="alice",
            recipient_addr="bob",
            value_list=(ValueRange(0, 49), ValueRange(50, 99)),
            tx_local_index=0,
            tx_time=1,
        )
        self.assertEqual(tx.sender_addr, "alice")
        self.assertEqual(len(tx.value_list), 2)

    def test_bundle_sidecar_tx_count_matches_tx_list(self) -> None:
        """验证BundleSidecar的tx_count自动设置为tx_list长度"""
        from EZ_V2.values import ValueRange

        tx1 = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        tx2 = OffChainTx("alice", "carol", (ValueRange(50, 99),), 1, 1)

        sidecar = BundleSidecar(
            sender_addr="alice",
            tx_list=(tx1, tx2),
        )
        self.assertEqual(sidecar.tx_count, 2)

    def test_bundle_envelope_signing_payload_includes_all_fields(self) -> None:
        """验证BundleEnvelope的signing_payload包含所有必要字段"""
        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )
        payload = envelope.signing_payload()
        self.assertIn("version", payload)
        self.assertIn("chain_id", payload)
        self.assertIn("seq", payload)
        self.assertIn("bundle_hash", payload)

    def test_account_leaf_with_null_refs_for_genesis(self) -> None:
        """验证创世账户的head_ref和prev_ref可以为NULL"""
        leaf = AccountLeaf(
            addr="alice",
            head_ref=None,
            prev_ref=None,
        )
        self.assertIsNone(leaf.head_ref)
        self.assertIsNone(leaf.prev_ref)

    def test_account_leaf_with_refs_after_first_transaction(self) -> None:
        """验证第一笔交易后账户的refs应正确设置"""
        ref = BundleRef(
            height=1,
            block_hash=b"\x11" * 32,
            bundle_hash=b"\x22" * 32,
            seq=1,
        )
        leaf = AccountLeaf(
            addr="alice",
            head_ref=ref,
            prev_ref=None,  # 第一笔交易prev_ref为NULL
        )
        self.assertEqual(leaf.head_ref.seq, 1)
        self.assertIsNone(leaf.prev_ref)


class EZV2TypesNegativeTests(unittest.TestCase):
    """
    [negative] 拒绝非法输入测试

    验证协议对象能正确拒绝非法输入，符合设计的安全要求
    """

    def test_bundle_ref_rejects_invalid_hash_length(self) -> None:
        """验证BundleRef拒绝非32字节的hash"""
        with self.assertRaises(ValueError):
            BundleRef(
                height=1,
                block_hash=b"\x11" * 31,  # 错误长度
                bundle_hash=b"\x22" * 32,
                seq=1,
            )

    def test_bundle_ref_rejects_negative_height(self) -> None:
        """验证BundleRef拒绝负数height"""
        with self.assertRaises(ValueError):
            BundleRef(
                height=-1,
                block_hash=b"\x11" * 32,
                bundle_hash=b"\x22" * 32,
                seq=1,
            )

    def test_bundle_ref_rejects_non_positive_seq(self) -> None:
        """验证BundleRef拒绝seq<=0"""
        with self.assertRaises(ValueError):
            BundleRef(
                height=1,
                block_hash=b"\x11" * 32,
                bundle_hash=b"\x22" * 32,
                seq=0,
            )

    def test_off_chain_tx_rejects_empty_sender(self) -> None:
        """验证OffChainTx拒绝空sender_addr"""
        from EZ_V2.values import ValueRange

        with self.assertRaises(ValueError):
            OffChainTx(
                sender_addr="",
                recipient_addr="bob",
                value_list=(ValueRange(0, 49),),
                tx_local_index=0,
                tx_time=1,
            )

    def test_off_chain_tx_rejects_empty_value_list(self) -> None:
        """验证OffChainTx拒绝空value_list"""
        with self.assertRaises(ValueError):
            OffChainTx(
                sender_addr="alice",
                recipient_addr="bob",
                value_list=(),
                tx_local_index=0,
                tx_time=1,
            )

    def test_off_chain_tx_rejects_unsorted_value_list(self) -> None:
        """验证OffChainTx拒绝未排序的value_list"""
        from EZ_V2.values import ValueRange

        with self.assertRaises(ValueError):
            OffChainTx(
                sender_addr="alice",
                recipient_addr="bob",
                value_list=(ValueRange(50, 99), ValueRange(0, 49)),  # 未排序
                tx_local_index=0,
                tx_time=1,
            )

    def test_off_chain_tx_rejects_overlapping_value_ranges(self) -> None:
        """验证OffChainTx拒绝重叠的value_list"""
        from EZ_V2.values import ValueRange

        with self.assertRaises(ValueError):
            OffChainTx(
                sender_addr="alice",
                recipient_addr="bob",
                value_list=(ValueRange(0, 49), ValueRange(30, 79)),  # 重叠
                tx_local_index=0,
                tx_time=1,
            )

    def test_bundle_sidecar_rejects_sender_mismatch(self) -> None:
        """验证BundleSidecar拒绝tx中的sender_addr与sidecar不一致"""
        from EZ_V2.values import ValueRange

        tx = OffChainTx("bob", "carol", (ValueRange(0, 49),), 0, 1)

        with self.assertRaises(ValueError):
            BundleSidecar(
                sender_addr="alice",  # 与tx.sender_addr不一致
                tx_list=(tx,),
            )

    def test_bundle_sidecar_rejects_tx_count_mismatch(self) -> None:
        """验证BundleSidecar拒绝显式tx_count与实际tx_list长度不符"""
        from EZ_V2.values import ValueRange

        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)

        with self.assertRaises(ValueError):
            BundleSidecar(
                sender_addr="alice",
                tx_list=(tx,),
                tx_count=2,  # 与实际长度不符
            )

    def test_bundle_envelope_rejects_invalid_hash_length(self) -> None:
        """验证BundleEnvelope拒绝非32字节的bundle_hash"""
        with self.assertRaises(ValueError):
            BundleEnvelope(
                version=1,
                chain_id=7001,
                seq=1,
                expiry_height=100,
                fee=1,
                anti_spam_nonce=123,
                bundle_hash=b"\x33" * 31,  # 错误长度
            )

    def test_bundle_envelope_rejects_non_positive_seq(self) -> None:
        """验证BundleEnvelope拒绝seq<=0"""
        with self.assertRaises(ValueError):
            BundleEnvelope(
                version=1,
                chain_id=7001,
                seq=0,  # 无效seq
                expiry_height=100,
                fee=1,
                anti_spam_nonce=123,
                bundle_hash=b"\x33" * 32,
            )

    def test_pending_bundle_context_rejects_empty_sender(self) -> None:
        """验证PendingBundleContext拒绝空sender_addr"""
        with self.assertRaises(ValueError):
            PendingBundleContext(
                sender_addr="",
                bundle_hash=b"\x11" * 32,
                seq=1,
                envelope=BundleEnvelope(
                    version=1, chain_id=7001, seq=1, expiry_height=100,
                    fee=1, anti_spam_nonce=123, bundle_hash=b"\x11" * 32,
                ),
                sidecar=BundleSidecar(
                    sender_addr="alice",
                    tx_list=(),
                ),
                sender_public_key_pem=b"",
                pending_record_ids=(),
                outgoing_record_ids=(),
                outgoing_values=(),
                created_at=1,
            )

    def test_account_leaf_rejects_empty_address(self) -> None:
        """验证AccountLeaf拒绝空addr"""
        with self.assertRaises(ValueError):
            AccountLeaf(
                addr="",
                head_ref=None,
                prev_ref=None,
            )


class EZV2TypesBoundaryTests(unittest.TestCase):
    """
    [boundary] 边界条件测试

    验证协议对象在边界条件下的行为正确
    """

    def test_off_chain_tx_with_single_value(self) -> None:
        """验证OffChainTx能处理单个ValueRange"""
        from EZ_V2.values import ValueRange

        tx = OffChainTx(
            sender_addr="alice",
            recipient_addr="bob",
            value_list=(ValueRange(0, 0),),  # 单值
            tx_local_index=0,
            tx_time=1,
        )
        self.assertEqual(len(tx.value_list), 1)

    def test_off_chain_tx_with_negative_tx_local_index_raises_error(self) -> None:
        """验证OffChainTx拒绝负数tx_local_index"""
        from EZ_V2.values import ValueRange

        with self.assertRaises(ValueError):
            OffChainTx(
                sender_addr="alice",
                recipient_addr="bob",
                value_list=(ValueRange(0, 49),),
                tx_local_index=-1,  # 无效
                tx_time=1,
            )

    def test_bundle_envelope_with_zero_numeric_fields(self) -> None:
        """验证BundleEnvelope允许某些字段为0"""
        envelope = BundleEnvelope(
            version=0,  # 允许为0
            chain_id=0,  # 允许为0
            seq=1,
            expiry_height=0,  # 允许为0
            fee=0,  # 允许为0
            anti_spam_nonce=0,  # 允许为0
            bundle_hash=b"\x33" * 32,
        )
        self.assertEqual(envelope.version, 0)
        self.assertEqual(envelope.fee, 0)


class EZV2TypesSignatureTests(unittest.TestCase):
    """
    [design-conformance] 签名附加测试

    验证BundleEnvelope的签名附加功能符合设计
    """

    def test_bundle_envelope_with_signature_creates_new_instance(self) -> None:
        """验证with_signature创建新的BundleEnvelope实例"""
        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )
        signature = b"\x44" * 64

        signed_envelope = envelope.with_signature(signature)

        # 验证创建了新实例
        self.assertIsNot(signed_envelope, envelope)
        self.assertEqual(signed_envelope.sig, signature)
        self.assertEqual(envelope.sig, b"")  # 原实例不变

    def test_bundle_envelope_preserves_other_fields_when_adding_signature(self) -> None:
        """验证添加签名时其他字段保持不变"""
        envelope = BundleEnvelope(
            version=1,
            chain_id=7001,
            seq=1,
            expiry_height=100,
            fee=1,
            anti_spam_nonce=123,
            bundle_hash=b"\x33" * 32,
        )
        signature = b"\x44" * 64

        signed_envelope = envelope.with_signature(signature)

        self.assertEqual(signed_envelope.version, envelope.version)
        self.assertEqual(signed_envelope.chain_id, envelope.chain_id)
        self.assertEqual(signed_envelope.seq, envelope.seq)
        self.assertEqual(signed_envelope.bundle_hash, envelope.bundle_hash)


if __name__ == "__main__":
    unittest.main()
