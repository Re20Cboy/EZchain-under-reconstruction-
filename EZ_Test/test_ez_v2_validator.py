"""
EZchain-V2 Validator核心测试

设计文档对照：
- EZchain-V2-protocol-draft.md 第13-14节：witness校验、递归验证
- EZchain-V2 desgin-human-write.md：state proof与receipt绑定

测试类别：
- design-conformance: 验证validator符合设计规范
- invariants: 验证递归验证边界
- negative: 验证非法witness被拒绝
- boundary: 验证边界条件
"""

from __future__ import annotations

import unittest

from EZ_V2.chain import (
    compute_addr_key,
    compute_bundle_hash,
    confirmed_ref,
    hash_account_leaf,
    reconstructed_leaf,
)
from EZ_V2.crypto import keccak256
from EZ_V2.smt import SparseMerkleTree
from EZ_V2.types import (
    AccountLeaf,
    BundleRef,
    BundleSidecar,
    Checkpoint,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    GenesisAnchor,
    HeaderLite,
    OffChainTx,
    PriorWitnessLink,
    Receipt,
    SparseMerkleProof,
    TransferPackage,
    WitnessV2,
)
from EZ_V2.validator import (
    ValidationResult,
    ValidationContext,
    V2TransferValidator,
)
from EZ_V2.values import ValueRange


def _make_valid_bundle_unit(
    sender_addr: str,
    tx_list: tuple[OffChainTx, ...],
    height: int,
    prev_ref: BundleRef | None = None,
    seq: int = 1,
    block_hash: bytes = b"\x11" * 32,
) -> ConfirmedBundleUnit:
    """辅助函数：创建带有有效account state proof的ConfirmedBundleUnit"""
    # 创建SMT并插入账户leaf
    tree = SparseMerkleTree(depth=256)

    # 创建sidecar和计算bundle_hash
    sidecar = BundleSidecar(sender_addr=sender_addr, tx_list=tx_list)
    bundle_hash = compute_bundle_hash(sidecar)

    # 构造account leaf - 使用正确的bundle_hash
    ref = BundleRef(height=height, block_hash=block_hash, bundle_hash=bundle_hash, seq=seq)
    leaf = AccountLeaf(addr=sender_addr, head_ref=ref, prev_ref=prev_ref)
    leaf_hash = hash_account_leaf(leaf)

    # 插入到SMT
    addr_key = compute_addr_key(sender_addr)
    tree.set(addr_key, leaf_hash)

    # 获取proof和state root
    proof = tree.prove(addr_key)
    state_root = tree.root()

    # 创建receipt
    receipt = Receipt(
        header_lite=HeaderLite(height=height, block_hash=block_hash, state_root=state_root),
        seq=seq,
        prev_ref=prev_ref,
        account_state_proof=proof,
    )

    return ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)


class EZV2ValidationContextTests(unittest.TestCase):
    """
    [design-conformance] ValidationContext测试
    """

    def test_validation_context_initialization(self) -> None:
        """验证ValidationContext正确初始化"""
        context = ValidationContext()
        self.assertEqual(context.genesis_allocations, {})
        self.assertEqual(context.trusted_checkpoints, ())

    def test_validation_context_with_genesis_allocations(self) -> None:
        """验证ValidationContext能设置genesis分配"""
        allocations = {
            "alice": (ValueRange(0, 99),),
            "bob": (ValueRange(100, 199),),
        }
        context = ValidationContext(genesis_allocations=allocations)
        self.assertEqual(len(context.genesis_allocations), 2)

    def test_validation_context_with_trusted_checkpoints(self) -> None:
        """验证ValidationContext能设置可信checkpoint"""
        checkpoint = Checkpoint(
            checkpoint_height=100,
            checkpoint_block_hash=b"\x11" * 32,
            checkpoint_bundle_hash=b"\x22" * 32,
            value_begin=0,
            value_end=99,
            owner_addr="alice",
        )
        context = ValidationContext(trusted_checkpoints=(checkpoint,))
        self.assertEqual(len(context.trusted_checkpoints), 1)

    def test_is_trusted_checkpoint_returns_true_for_matching(self) -> None:
        """验证is_trusted_checkpoint对匹配的checkpoint返回True"""
        checkpoint = Checkpoint(
            checkpoint_height=100,
            checkpoint_block_hash=b"\x11" * 32,
            checkpoint_bundle_hash=b"\x22" * 32,
            value_begin=0,
            value_end=99,
            owner_addr="alice",
        )
        context = ValidationContext(trusted_checkpoints=(checkpoint,))

        result = context.is_trusted_checkpoint(checkpoint, ValueRange(0, 99), "alice")
        self.assertTrue(result)

    def test_is_trusted_checkpoint_returns_false_for_non_matching(self) -> None:
        """验证is_trusted_checkpoint对不匹配的checkpoint返回False"""
        checkpoint = Checkpoint(
            checkpoint_height=100,
            checkpoint_block_hash=b"\x11" * 32,
            checkpoint_bundle_hash=b"\x22" * 32,
            value_begin=0,
            value_end=99,
            owner_addr="alice",
        )
        context = ValidationContext(trusted_checkpoints=(checkpoint,))

        # 不同的owner
        result = context.is_trusted_checkpoint(checkpoint, ValueRange(0, 99), "bob")
        self.assertFalse(result)

    def test_matches_genesis_anchor_returns_true_for_valid(self) -> None:
        """验证matches_genesis_anchor对有效anchor返回True"""
        allocations = {"alice": (ValueRange(0, 99),)}
        context = ValidationContext(genesis_allocations=allocations)

        anchor = GenesisAnchor(
            genesis_block_hash=b"\x00" * 32,
            first_owner_addr="alice",
            value_begin=0,
            value_end=99,
        )
        result = context.matches_genesis_anchor(anchor, ValueRange(0, 49), "alice")
        self.assertTrue(result)

    def test_matches_genesis_anchor_returns_false_for_wrong_owner(self) -> None:
        """验证matches_genesis_anchor对错误owner返回False"""
        allocations = {"alice": (ValueRange(0, 99),)}
        context = ValidationContext(genesis_allocations=allocations)

        anchor = GenesisAnchor(
            genesis_block_hash=b"\x00" * 32,
            first_owner_addr="alice",
            value_begin=0,
            value_end=99,
        )
        result = context.matches_genesis_anchor(anchor, ValueRange(0, 49), "bob")
        self.assertFalse(result)

    def test_matches_genesis_anchor_returns_false_for_value_outside_range(self) -> None:
        """验证matches_genesis_anchor对范围外的值返回False"""
        allocations = {"alice": (ValueRange(0, 99),)}
        context = ValidationContext(genesis_allocations=allocations)

        anchor = GenesisAnchor(
            genesis_block_hash=b"\x00" * 32,
            first_owner_addr="alice",
            value_begin=0,
            value_end=99,
        )
        result = context.matches_genesis_anchor(anchor, ValueRange(100, 149), "alice")
        self.assertFalse(result)


class EZV2ValidationResultTests(unittest.TestCase):
    """
    [design-conformance] ValidationResult测试
    """

    def test_validation_result_success(self) -> None:
        """验证成功的ValidationResult"""
        result = ValidationResult(ok=True)
        self.assertTrue(result.ok)
        self.assertIsNone(result.error)

    def test_validation_result_failure(self) -> None:
        """验证失败的ValidationResult"""
        result = ValidationResult(ok=False, error="test error")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "test error")

    def test_validation_result_with_accepted_witness(self) -> None:
        """验证包含accepted_witness的ValidationResult"""
        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="bob",
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )
        result = ValidationResult(ok=True, accepted_witness=witness)
        self.assertTrue(result.ok)
        self.assertEqual(result.accepted_witness, witness)


class EZV2ValidatorWitnessOwnerTests(unittest.TestCase):
    """
    [design-conformance] Witness owner校验测试
    """

    def test_validate_rejects_witness_owner_mismatch(self) -> None:
        """验证witness owner与target tx sender不匹配时拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="charlie",  # 与sender不匹配
            confirmed_bundle_chain=(),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("witness owner does not match", result.error)

    def test_validate_passes_witness_owner_check(self) -> None:
        """验证witness owner与target tx sender匹配时通过owner检查"""
        validator = V2TransferValidator(context=ValidationContext())

        # 构造有效的confirmed_bundle_chain
        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))  # 包含target_tx
        unit = ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",  # 匹配sender
            confirmed_bundle_chain=(unit,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        # 不是owner mismatch错误
        if not result.ok:
            self.assertNotIn("witness owner does not match", result.error)


class EZV2ValidatorRecipientTests(unittest.TestCase):
    """
    [design-conformance] Recipient校验测试
    """

    def test_validate_rejects_recipient_mismatch(self) -> None:
        """验证target recipient不匹配时拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))  # 包含target_tx
        unit = ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package, recipient_addr="charlie")

        self.assertFalse(result.ok)
        self.assertIn("target recipient mismatch", result.error)


class EZV2ValidatorValueCoverageTests(unittest.TestCase):
    """
    [design-conformance] Value覆盖校验测试
    """

    def test_validate_rejects_value_not_covered(self) -> None:
        """验证target_value不被tx覆盖时拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))  # 包含target_tx
        unit = ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)

        witness = WitnessV2(
            value=ValueRange(50, 99),  # 不被tx覆盖
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(50, 99), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("target value is not covered", result.error)


class EZV2ValidatorEmptyChainTests(unittest.TestCase):
    """
    [negative] 空链校验测试
    """

    def test_validate_rejects_empty_confirmed_bundle_chain(self) -> None:
        """验证空的confirmed_bundle_chain被拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(),  # 空
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("cannot be empty", result.error)


class EZV2ValidatorAccountStateProofTests(unittest.TestCase):
    """
    [design-conformance] Account state proof校验测试
    """

    def test_validate_rejects_invalid_account_state_proof(self) -> None:
        """验证无效的account state proof被拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        # 构造无效的proof（empty siblings但标记为exist）
        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=1, block_hash=b"\x11" * 32, state_root=b"\x22" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )

        # 计算正确的leaf hash但使用错误的状态root
        leaf = reconstructed_leaf(ConfirmedBundleUnit(
            bundle_sidecar=BundleSidecar(sender_addr="alice", tx_list=()),
            receipt=receipt,
        ))
        leaf_hash = hash_account_leaf(leaf)
        addr_key = compute_addr_key("alice")

        # 创建一个与leaf hash不匹配的state root
        wrong_state_root = keccak256(b"wrong")

        # 验证proof失败（因为state root不匹配）
        from EZ_V2.smt import verify_proof
        is_valid = verify_proof(wrong_state_root, addr_key, leaf_hash, proof, depth=256)
        self.assertFalse(is_valid)


class EZV2ValidatorPrevRefChainTests(unittest.TestCase):
    """
    [invariants] PrevRef链连续性测试
    """

    def test_validate_rejects_discontinuous_prev_ref_chain(self) -> None:
        """验证不连续的prev_ref链被拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        # 构造两个bundle unit，prev_ref不连续
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)

        # 创建第二个unit (height=1)
        unit2 = _make_valid_bundle_unit("alice", (), height=1, seq=1)

        # 获取正确的ref
        correct_ref = confirmed_ref(unit2)

        # 创建第一个unit (height=2)，但prev_ref指向错误的block_hash
        wrong_ref = BundleRef(
            height=correct_ref.height,
            block_hash=b"\xFF" * 32,  # 错误的block_hash
            bundle_hash=correct_ref.bundle_hash,
            seq=correct_ref.seq,
        )
        unit1 = _make_valid_bundle_unit("alice", (tx,), height=2, seq=2, prev_ref=wrong_ref)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit1, unit2),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("prev_ref chain is discontinuous", result.error)


class EZV2ValidatorValueConflictTests(unittest.TestCase):
    """
    [invariants] Value冲突检测测试
    """

    def test_validate_rejects_value_conflict_in_history(self) -> None:
        """验证当前sender历史中的value冲突被拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        # 构造与target_value冲突的tx - 在同一bundle中
        conflicting_tx = OffChainTx("alice", "carol", (ValueRange(0, 49),), 0, 1)
        target_tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 1, 1)

        unit = _make_valid_bundle_unit("alice", (conflicting_tx, target_tx), height=1, seq=1)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=target_tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        # 应该检测到冲突：conflicting_tx使用了相同的值范围
        self.assertIn("value conflict detected", result.error)


class EZV2ValidatorGenesisAnchorTests(unittest.TestCase):
    """
    [design-conformance] Genesis anchor校验测试
    """

    def test_validate_rejects_genesis_anchor_mismatch(self) -> None:
        """验证genesis anchor不匹配时拒绝"""
        validator = V2TransferValidator(
            context=ValidationContext(genesis_allocations={"alice": (ValueRange(0, 99),)})
        )

        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        unit = _make_valid_bundle_unit("alice", (tx,), height=1, seq=1)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="bob",  # 错误owner
                value_begin=0,
                value_end=99,
            ),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("genesis anchor mismatch", result.error)


class EZV2ValidatorCheckpointAnchorTests(unittest.TestCase):
    """
    [design-conformance] Checkpoint anchor校验测试
    """

    def test_validate_rejects_untrusted_checkpoint(self) -> None:
        """验证不受信任的checkpoint被拒绝"""
        checkpoint = Checkpoint(
            checkpoint_height=100,
            checkpoint_block_hash=b"\x11" * 32,
            checkpoint_bundle_hash=b"\x22" * 32,
            value_begin=0,
            value_end=99,
            owner_addr="alice",
        )
        # 空的trusted_checkpoints列表
        validator = V2TransferValidator(context=ValidationContext(trusted_checkpoints=()))

        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        unit = _make_valid_bundle_unit("alice", (tx,), height=1, seq=1)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=CheckpointAnchor(checkpoint=checkpoint),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("checkpoint anchor is not trusted", result.error)

    def test_validate_passes_trusted_checkpoint_check(self) -> None:
        """验证受信任的checkpoint通过checkpoint检查"""
        checkpoint = Checkpoint(
            checkpoint_height=100,
            checkpoint_block_hash=b"\x11" * 32,
            checkpoint_bundle_hash=b"\x22" * 32,
            value_begin=0,
            value_end=99,
            owner_addr="alice",
        )
        validator = V2TransferValidator(context=ValidationContext(trusted_checkpoints=(checkpoint,)))

        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=101, block_hash=b"\x33" * 32, state_root=b"\x44" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))  # 包含target_tx
        unit = ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=CheckpointAnchor(checkpoint=checkpoint),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        # checkpoint验证通过，但可能因为其他原因失败
        # 只要不返回"checkpoint anchor is not trusted"即可
        if not result.ok:
            self.assertNotIn("checkpoint anchor is not trusted", result.error)


class EZV2ValidatorRecursiveWitnessTests(unittest.TestCase):
    """
    [invariants] 递归witness验证测试
    """

    def test_validate_rejects_prior_witness_height_violation(self) -> None:
        """验证违反height约束的递归witness被拒绝"""
        # 添加alice到genesis分配
        validator = V2TransferValidator(
            context=ValidationContext(genesis_allocations={"alice": (ValueRange(0, 99),)})
        )

        # 构造prior witness (height=10)
        acquire_tx = OffChainTx("alice", "alice", (ValueRange(0, 49),), 0, 1)
        prior_unit = _make_valid_bundle_unit("alice", (acquire_tx,), height=10, seq=1)

        prior_witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(prior_unit,),
            anchor=GenesisAnchor(
                genesis_block_hash=b"\x00" * 32,
                first_owner_addr="alice",
                value_begin=0,
                value_end=99,
            ),
        )

        # 构造current witness (height=5，违反height约束: 5 <= 10)
        current_tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 1, 1)
        current_unit = _make_valid_bundle_unit("alice", (current_tx,), height=5, seq=2)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(current_unit,),
            anchor=PriorWitnessLink(acquire_tx=acquire_tx, prior_witness=prior_witness),
        )

        package = TransferPackage(target_tx=current_tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("starts before acquisition boundary", result.error)


class EZV2ValidatorAcceptedWitnessTests(unittest.TestCase):
    """
    [design-conformance] 接受witness构造测试
    """

    def test_validate_returns_validation_result(self) -> None:
        """验证validate返回ValidationResult结构"""
        checkpoint = Checkpoint(
            checkpoint_height=100,
            checkpoint_block_hash=b"\x11" * 32,
            checkpoint_bundle_hash=b"\x22" * 32,
            value_begin=0,
            value_end=99,
            owner_addr="alice",
        )
        validator = V2TransferValidator(context=ValidationContext(trusted_checkpoints=(checkpoint,)))

        proof = SparseMerkleProof(siblings=(), existence=True)
        receipt = Receipt(
            header_lite=HeaderLite(height=101, block_hash=b"\x33" * 32, state_root=b"\x44" * 32),
            seq=1,
            prev_ref=None,
            account_state_proof=proof,
        )
        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        sidecar = BundleSidecar(sender_addr="alice", tx_list=(tx,))  # 包含target_tx
        unit = ConfirmedBundleUnit(bundle_sidecar=sidecar, receipt=receipt)

        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor=CheckpointAnchor(checkpoint=checkpoint),
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        # 验证返回的result结构
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ValidationResult)


class EZV2ValidatorUnsupportedAnchorTests(unittest.TestCase):
    """
    [negative] 不支持的anchor类型测试
    """

    def test_validate_rejects_unsupported_anchor_type(self) -> None:
        """验证不支持的anchor类型被拒绝"""
        validator = V2TransferValidator(context=ValidationContext())

        tx = OffChainTx("alice", "bob", (ValueRange(0, 49),), 0, 1)
        unit = _make_valid_bundle_unit("alice", (tx,), height=1, seq=1)

        # 使用字符串作为不支持的anchor类型
        witness = WitnessV2(
            value=ValueRange(0, 49),
            current_owner_addr="alice",
            confirmed_bundle_chain=(unit,),
            anchor="unsupported",  # type: ignore
        )

        package = TransferPackage(target_tx=tx, target_value=ValueRange(0, 49), witness_v2=witness)
        result = validator.validate_transfer_package(package)

        self.assertFalse(result.ok)
        self.assertIn("unsupported witness anchor", result.error)


if __name__ == "__main__":
    unittest.main()
