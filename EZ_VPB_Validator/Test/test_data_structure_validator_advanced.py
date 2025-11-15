#!/usr/bin/env python3
"""
Advanced Test Suite for DataStructureValidator

Hacker's perspective: Testing edge cases, malicious inputs, and potential vulnerabilities
to ensure DataStructureValidator is robust against sophisticated attacks.

Author: Advanced Security Testing
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
import hashlib

# Add project paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from EZ_VPB_Validator.steps.data_structure_validator_01 import DataStructureValidator
from EZ_Value.Value import Value, ValueState
from EZ_Proof.Proofs import Proofs
from EZ_Proof.ProofUnit import ProofUnit
from EZ_BlockIndex.BlockIndexList import BlockIndexList


class TestDataStructureValidatorHacks(unittest.TestCase):
    """
    Hacker's perspective test suite for DataStructureValidator
    """

    def setUp(self):
        """Set up test environment"""
        self.validator = DataStructureValidator()

    def create_mock_proof_unit(self, owner="0x1234567890123456789012345678901234567890"):
        """Create a mock proof unit for testing"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = owner
        mock_multi_txns.digest = "a" * 64
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = ["0x" + "a" * 64, "0x" + "b" * 64]

        return Mock(spec=ProofUnit, owner=owner, owner_multi_txns=mock_multi_txns,
                   owner_mt_proof=mock_mt_proof, unit_id="0x" + "c" * 64, reference_count=1)

    def create_mock_proofs(self, proof_count=3):
        """Create mock proofs object"""
        mock_proofs = Mock(spec=Proofs)
        mock_proofs.value_id = "test_value_id"
        mock_proofs.get_proof_units.return_value = [self.create_mock_proof_unit() for _ in range(proof_count)]
        return mock_proofs

    # ========== VALUE VALIDATION ATTACKS ==========

    def test_value_attack_malformed_hex_strings(self):
        """Test various malformed hex strings that might bypass validation"""
        # Valid value for reference
        valid_value = Value("0x100", 10)

        # Create malicious values with tricky hex strings
        malicious_hex_cases = [
            # Leading/trailing whitespace
            lambda: Value(" 0x100 ", 10),
            # Mixed case 0X prefix
            lambda: Value("0X100", 10),
            # Extra 0x prefix
            lambda: Value("0x0x100", 10),
            # Invalid hex characters
            lambda: Value("0xGHI", 10),
            # Empty hex
            lambda: Value("0x", 10),
            # Only prefix
            lambda: Value("0x", 1),
            # Negative numbers in hex (should be invalid)
            lambda: Value("-0x100", 10),
            # Plus prefix
            lambda: Value("+0x100", 10),
            # Very long hex string (potential buffer overflow)
            lambda: Value("0x" + "1" * 1000, 10),
        ]

        for case in malicious_hex_cases:
            with self.subTest(case=case.__name__):
                mock_proofs = self.create_mock_proofs(1)
                mock_block_list = Mock(spec=BlockIndexList)
                mock_block_list.index_lst = [1]

                try:
                    malicious_value = case()
                    # Should fail validation
                    result, error = self.validator.validate_basic_data_structure(
                        malicious_value, mock_proofs, mock_block_list
                    )
                    self.assertFalse(result, f"Security breach: {case.__name__} passed validation")
                except (ValueError, TypeError, AttributeError):
                    # Expected to fail during object creation or validation
                    pass

    def test_value_attack_boundary_conditions(self):
        """Test boundary conditions that might expose logic flaws"""
        mock_proofs = self.create_mock_proofs(1)
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1]

        boundary_cases = [
            # Zero value (should be invalid)
            lambda: Value("0x1", 0),
            # Negative value (should cause creation error)
            lambda: Value("0x1", -1),
            # Value of 1 (minimum valid)
            lambda: Value("0x1", 1),
            # Very large value (potential overflow)
            lambda: Value("0x1", 2**63 - 1),
            # Same begin and end index (invalid, value_num should be at least 1)
            lambda: Value("0x100", 0),  # This will have begin_index == end_index
        ]

        for case in boundary_cases:
            with self.subTest(case=case.__name__):
                try:
                    test_value = case()
                    result, error = self.validator.validate_basic_data_structure(
                        test_value, mock_proofs, mock_block_list
                    )
                    # Only case with value_num=1 should pass
                    if case.__name__.endswith("1"):
                        self.assertTrue(result, f"Valid boundary case failed: {case.__name__}")
                    else:
                        self.assertFalse(result, f"Invalid boundary case passed: {case.__name__}")
                except (ValueError, TypeError):
                    # Expected for invalid cases
                    pass

    def test_value_attack_state_manipulation(self):
        """Test state manipulation attacks"""
        mock_proofs = self.create_mock_proofs(1)
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1]

        valid_value = Value("0x100", 10)

        # Test various state attacks
        state_attacks = [
            # Replace enum with string
            lambda: setattr(valid_value, 'state', 'UNSPENT'),
            # Replace with integer
            lambda: setattr(valid_value, 'state', 0),
            # Replace with None
            lambda: setattr(valid_value, 'state', None),
            # Replace with fake enum
            lambda: setattr(valid_value, 'state', 'FAKE_STATE'),
            # Delete state attribute
            lambda: delattr(valid_value, 'state'),
        ]

        for attack in state_attacks:
            with self.subTest(attack=attack.__name__):
                try:
                    # Reset to valid state first
                    valid_value.state = ValueState.UNSPENT
                    attack()
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, mock_proofs, mock_block_list
                    )
                    self.assertFalse(result, f"State attack succeeded: {attack.__name__}")
                except (AttributeError, TypeError):
                    # Expected for invalid states
                    pass

    def test_value_attack_index_relationship_violations(self):
        """Test attacks that violate index relationships"""
        mock_proofs = self.create_mock_proofs(1)
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1]

        valid_value = Value("0x100", 10)

        # Index relationship attacks
        index_attacks = [
            # Swap begin and end (end < begin)
            lambda: setattr(valid_value, 'end_index', '0x50'),
            # Make end equal to begin
            lambda: setattr(valid_value, 'end_index', '0x100'),
            # Corrupt end_index format
            lambda: setattr(valid_value, 'end_index', '0xGHI'),
            # Set end_index to None
            lambda: setattr(valid_value, 'end_index', None),
            # Set begin_index to None
            lambda: setattr(valid_value, 'begin_index', None),
        ]

        for attack in index_attacks:
            with self.subTest(attack=attack.__name__):
                try:
                    # Reset to valid state
                    valid_value.end_index = valid_value.get_end_index(valid_value.begin_index, valid_value.value_num)
                    attack()
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, mock_proofs, mock_block_list
                    )
                    self.assertFalse(result, f"Index attack succeeded: {attack.__name__}")
                except (AttributeError, TypeError, ValueError):
                    # Expected
                    pass

    # ========== PROOFS VALIDATION ATTACKS ==========

    def test_proofs_attack_malformed_objects(self):
        """Test attacks using malformed Proofs objects"""
        valid_value = Value("0x100", 10)

        # Malformed proofs attacks
        malformed_proofs = [
            # Wrong object type
            lambda: "not_a_proofs_object",
            # Dict masquerading as proofs
            lambda: {'value_id': 'test', 'proof_units': []},
            # None
            lambda: None,
            # Empty object
            lambda: Mock(spec=object),
            # Proofs with invalid value_id
            lambda: self._create_proofs_with_invalid_value_id(),
            # Proofs that raise exceptions during get_proof_units
            lambda: self._create_proofs_that_throws(),
        ]

        for attack in malformed_proofs:
            with self.subTest(attack=attack.__name__):
                mock_block_list = Mock(spec=BlockIndexList)
                mock_block_list.index_lst = [1]

                try:
                    malicious_proofs = attack()
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, malicious_proofs, mock_block_list
                    )
                    self.assertFalse(result, f"Proofs attack succeeded: {attack.__name__}")
                except (AttributeError, TypeError):
                    # Expected
                    pass

    def test_proof_unit_attack_sophisticated_fakes(self):
        """Test sophisticated ProofUnit attacks"""
        valid_value = Value("0x100", 10)

        # Create mock proofs with malicious proof units
        malicious_proof_units = [
            # ProofUnit with invalid owner address formats
            self._create_proof_unit_with_invalid_address(""),
            self._create_proof_unit_with_invalid_address("0x123"),  # Too short
            self._create_proof_unit_with_invalid_address("0x" + "1" * 41),  # Too long
            self._create_proof_unit_with_invalid_address("0xGHIJK"),  # Invalid chars
            self._create_proof_unit_with_invalid_address("123456"),  # Missing 0x prefix
            self._create_proof_unit_with_invalid_address("0x" + "z" * 40),  # Non-hex

            # ProofUnit with mismatched sender
            self._create_proof_unit_with_mismatched_sender(),

            # ProofUnit with invalid digests
            self._create_proof_unit_with_invalid_digest(None),
            self._create_proof_unit_with_invalid_digest(""),
            self._create_proof_unit_with_invalid_digest("invalid"),
            self._create_proof_unit_with_invalid_digest("0x" + "g" * 62),  # Invalid hex in digest

            # ProofUnit with invalid merkle proof lists
            self._create_proof_unit_with_invalid_mt_proof([]),  # Empty list
            self._create_proof_unit_with_invalid_mt_proof(["invalid_hash"]),  # Invalid hash format
            self._create_proof_unit_with_invalid_mt_proof([None]),  # None in list

            # ProofUnit with invalid unit_id
            self._create_proof_unit_with_invalid_unit_id(""),
            self._create_proof_unit_with_invalid_unit_id("invalid"),
            self._create_proof_unit_with_invalid_unit_id("0x" + "1" * 63),  # Too short

            # ProofUnit with invalid reference_count
            self._create_proof_unit_with_invalid_reference_count(0),
            self._create_proof_unit_with_invalid_reference_count(-1),
            self._create_proof_unit_with_invalid_reference_count("invalid"),
        ]

        for i, malicious_proof_unit in enumerate(malicious_proof_units):
            with self.subTest(proof_unit=i):
                mock_proofs = Mock(spec=Proofs)
                mock_proofs.value_id = "test_value_id"
                mock_proofs.get_proof_units.return_value = [malicious_proof_unit]

                mock_block_list = Mock(spec=BlockIndexList)
                mock_block_list.index_lst = [1]

                try:
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, mock_proofs, mock_block_list
                    )
                    self.assertFalse(result, f"ProofUnit attack {i} succeeded")
                except (AttributeError, TypeError):
                    # Expected
                    pass

    # ========== BLOCK INDEX LIST ATTACKS ==========

    def test_block_index_list_attack_boundary_conditions(self):
        """Test BlockIndexList boundary condition attacks"""
        valid_value = Value("0x100", 10)
        mock_proofs = self.create_mock_proofs(1)

        # Boundary condition attacks
        boundary_attacks = [
            # Empty index list
            lambda: self._create_block_index_with_indices([]),
            # Single index (valid but edge case)
            lambda: self._create_block_index_with_indices([0]),
            # Negative indices
            lambda: self._create_block_index_with_indices([-1, -2]),
            # Very large indices (potential overflow)
            lambda: self._create_block_index_with_indices([2**31 - 1, 2**31]),
            # Duplicate indices (should fail strict increasing)
            lambda: self._create_block_index_with_indices([1, 1, 2]),
            # Descending order
            lambda: self._create_block_index_with_indices([5, 4, 3, 2, 1]),
            # Non-sequential but increasing
            lambda: self._create_block_index_with_indices([1, 5, 10]),
        ]

        for i, attack in enumerate(boundary_attacks):
            with self.subTest(attack=i, description=attack.__name__):
                try:
                    malicious_block_list = attack()
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, mock_proofs, malicious_block_list
                    )
                    # Only single index [0] should pass (others either have invalid indices or count mismatch)
                    if i == 1:  # Single index [0]
                        self.assertTrue(result, f"Valid boundary case failed: {attack.__name__}")
                    else:
                        self.assertFalse(result, f"Invalid boundary case passed: {attack.__name__}")
                except (AttributeError, TypeError):
                    # Expected
                    pass

    def test_block_index_list_attack_owner_manipulation(self):
        """Test sophisticated owner manipulation attacks"""
        valid_value = Value("0x100", 10)
        mock_proofs = self.create_mock_proofs(3)

        # Owner manipulation attacks
        owner_attacks = [
            # Invalid owner addresses in string format
            lambda: self._create_block_index_with_owner(""),
            lambda: self._create_block_index_with_owner("invalid_address"),
            lambda: self._create_block_index_with_owner("0x123"),  # Too short
            lambda: self._create_block_index_with_owner("0x" + "z" * 40),  # Invalid hex

            # Invalid owner in list format
            lambda: self._create_block_index_with_owner_list([
                (1, ""),  # Empty address
                (2, "invalid"),  # Invalid format
                (3, "0x123"),  # Too short
                (4, None),  # None address
                (5, 123),  # Non-string address
            ]),

            # Block index not in index_lst
            lambda: self._create_block_index_with_unreferenced_owner(),

            # Non-monotonic owner block indices
            lambda: self._create_block_index_with_non_monotonic_owner(),
        ]

        for attack in owner_attacks:
            with self.subTest(attack=attack.__name__):
                try:
                    malicious_block_list = attack()
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, mock_proofs, malicious_block_list
                    )
                    self.assertFalse(result, f"Owner attack succeeded: {attack.__name__}")
                except (AttributeError, TypeError):
                    # Expected
                    pass

    # ========== VPB CONSISTENCY ATTACKS ==========

    def test_vpb_consistency_attack_count_mismatch(self):
        """Test attacks that violate count consistency between Proofs and BlockIndexList"""
        valid_value = Value("0x100", 10)

        # Count mismatch attacks
        mismatch_attacks = [
            # More proofs than indices
            (self.create_mock_proofs(5), [1, 2, 3]),
            # More indices than proofs
            (self.create_mock_proofs(2), [1, 2, 3, 4]),
            # Empty proofs with non-empty indices
            (self.create_mock_proofs(0), [1, 2]),
            # Non-empty proofs with empty indices
            (self.create_mock_proofs(3), []),
        ]

        for i, (mock_proofs, indices) in enumerate(mismatch_attacks):
            with self.subTest(attack=i):
                mock_block_list = Mock(spec=BlockIndexList)
                mock_block_list.index_lst = indices

                try:
                    result, error = self.validator.validate_basic_data_structure(
                        valid_value, mock_proofs, mock_block_list
                    )
                    self.assertFalse(result, f"Count mismatch attack {i} succeeded")
                except (AttributeError, TypeError):
                    # Expected
                    pass

    # ========== VALID EDGE CASES (Should Pass) ==========

    def test_valid_edge_cases_weird_but_correct(self):
        """Test weird but valid edge cases that should pass validation"""

        # Valid but unusual cases
        valid_edge_cases = [
            # Single value with single proof and single index
            (
                Value("0x1", 1),  # value_num=1 is valid (begin_index == end_index)
                self.create_mock_proofs(1),
                self._create_block_index_with_indices([1])
            ),
            # Large but valid values
            (
                Value("0x1000", 1000000),
                self.create_mock_proofs(1),
                self._create_block_index_with_indices([1000])
            ),
            # Maximum valid hex values
            (
                Value("0xFFFFFFFFFFFFFFFF", 1),
                self.create_mock_proofs(1),
                self._create_block_index_with_indices([1])
            ),
        ]

        for i, (value, proofs, block_list) in enumerate(valid_edge_cases):
            with self.subTest(case=i):
                try:
                    result, error = self.validator.validate_basic_data_structure(
                        value, proofs, block_list
                    )
                    self.assertTrue(result, f"Valid edge case {i} failed: {error}")
                except Exception as e:
                    self.fail(f"Valid edge case {i} raised exception: {e}")

    # ========== Helper Methods for Creating Malicious Objects ==========

    def _create_proofs_with_invalid_value_id(self):
        """Create Proofs object with invalid value_id"""
        mock_proofs = Mock(spec=Proofs)
        mock_proofs.value_id = ""  # Empty value_id
        mock_proofs.get_proof_units.return_value = [self.create_mock_proof_unit()]
        return mock_proofs

    def _create_proofs_that_throws(self):
        """Create Proofs object that throws exception during get_proof_units"""
        mock_proofs = Mock(spec=Proofs)
        mock_proofs.value_id = "test"
        mock_proofs.get_proof_units.side_effect = Exception("Simulated error")
        return mock_proofs

    def _create_proof_unit_with_invalid_address(self, address):
        """Create ProofUnit with invalid owner address"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = address
        mock_multi_txns.digest = "a" * 64
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = ["0x" + "a" * 64]

        return Mock(spec=ProofUnit, owner=address, owner_multi_txns=mock_multi_txns,
                   owner_mt_proof=mock_mt_proof, unit_id="0x" + "c" * 64, reference_count=1)

    def _create_proof_unit_with_mismatched_sender(self):
        """Create ProofUnit where sender doesn't match owner"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = "0xDIFFERENTADDRESS123456789012345678901234567890"
        mock_multi_txns.digest = "a" * 64
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = ["0x" + "a" * 64]

        return Mock(spec=ProofUnit, owner="0x1234567890123456789012345678901234567890",
                   owner_multi_txns=mock_multi_txns, owner_mt_proof=mock_mt_proof,
                   unit_id="0x" + "c" * 64, reference_count=1)

    def _create_proof_unit_with_invalid_digest(self, digest):
        """Create ProofUnit with invalid digest"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = "0x1234567890123456789012345678901234567890"
        mock_multi_txns.digest = digest
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = ["0x" + "a" * 64]

        return Mock(spec=ProofUnit, owner="0x1234567890123456789012345678901234567890",
                   owner_multi_txns=mock_multi_txns, owner_mt_proof=mock_mt_proof,
                   unit_id="0x" + "c" * 64, reference_count=1)

    def _create_proof_unit_with_invalid_mt_proof(self, mt_prf_list):
        """Create ProofUnit with invalid merkle proof list"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = "0x1234567890123456789012345678901234567890"
        mock_multi_txns.digest = "a" * 64
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = mt_prf_list

        return Mock(spec=ProofUnit, owner="0x1234567890123456789012345678901234567890",
                   owner_multi_txns=mock_multi_txns, owner_mt_proof=mock_mt_proof,
                   unit_id="0x" + "c" * 64, reference_count=1)

    def _create_proof_unit_with_invalid_unit_id(self, unit_id):
        """Create ProofUnit with invalid unit_id"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = "0x1234567890123456789012345678901234567890"
        mock_multi_txns.digest = "a" * 64
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = ["0x" + "a" * 64]

        return Mock(spec=ProofUnit, owner="0x1234567890123456789012345678901234567890",
                   owner_multi_txns=mock_multi_txns, owner_mt_proof=mock_mt_proof,
                   unit_id=unit_id, reference_count=1)

    def _create_proof_unit_with_invalid_reference_count(self, ref_count):
        """Create ProofUnit with invalid reference count"""
        mock_multi_txns = Mock()
        mock_multi_txns.sender = "0x1234567890123456789012345678901234567890"
        mock_multi_txns.digest = "a" * 64
        mock_multi_txns.multi_txns = []

        mock_mt_proof = Mock()
        mock_mt_proof.mt_prf_list = ["0x" + "a" * 64]

        return Mock(spec=ProofUnit, owner="0x1234567890123456789012345678901234567890",
                   owner_multi_txns=mock_multi_txns, owner_mt_proof=mock_mt_proof,
                   unit_id="0x" + "c" * 64, reference_count=ref_count)

    def _create_block_index_with_indices(self, indices):
        """Create BlockIndexList with specific indices"""
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = indices
        mock_block_list.owner = None
        return mock_block_list

    def _create_block_index_with_owner(self, owner):
        """Create BlockIndexList with specific owner"""
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1, 2, 3]
        mock_block_list.owner = owner
        return mock_block_list

    def _create_block_index_with_owner_list(self, owner_list):
        """Create BlockIndexList with owner list"""
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1, 2, 3, 4]
        mock_block_list.owner = owner_list
        return mock_block_list

    def _create_block_index_with_unreferenced_owner(self):
        """Create BlockIndexList where owner references non-existent block index"""
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1, 2, 3]
        mock_block_list.owner = [(99, "0x1234567890123456789012345678901234567890")]  # Block 99 not in indices
        return mock_block_list

    def _create_block_index_with_non_monotonic_owner(self):
        """Create BlockIndexList with non-monotonic owner block indices"""
        mock_block_list = Mock(spec=BlockIndexList)
        mock_block_list.index_lst = [1, 2, 3, 4, 5]
        mock_block_list.owner = [
            (3, "0x1234567890123456789012345678901234567890"),
            (2, "0x1234567890123456789012345678901234567890"),  # Not monotonic
        ]
        return mock_block_list


if __name__ == '__main__':
    print("=" * 80)
    print("RUNNING ADVANCED HACKER-PERSPECTIVE TESTS FOR DataStructureValidator")
    print("=" * 80)
    print("These tests attempt to bypass validation using sophisticated techniques.")
    print("All malicious cases should FAIL, and all valid cases should PASS.")
    print("=" * 80)

    unittest.main(verbosity=2)