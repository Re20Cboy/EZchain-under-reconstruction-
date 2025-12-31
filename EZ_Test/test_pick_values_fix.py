#!/usr/bin/env python3
"""
Simple test script to verify the fixes for AccountPickValues
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from EZ_VPB.values.AccountPickValues import AccountPickValues
from EZ_VPB.values.AccountValueCollection import AccountValueCollection
from EZ_VPB.values.Value import Value, ValueState


def test_subset_sum_algorithm():
    """Test that the subset sum algorithm finds exact matches"""
    print("=" * 60)
    print("Test 1: Subset Sum Algorithm")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Add test values
    values = [
        Value("0x1000", 100, ValueState.UNSPENT),
        Value("0x2000", 200, ValueState.UNSPENT),
        Value("0x3000", 150, ValueState.UNSPENT),
        Value("0x3001", 50, ValueState.UNSPENT),
        Value("0x4000", 300, ValueState.UNSPENT),
    ]
    apv.add_values_from_list(values)

    # Test 1: Simple exact match (200)
    print("\n1. Testing exact match of 200...")
    selected, total = apv._select_values_without_change(values, 200)
    assert total == 200, f"Expected 200, got {total}"
    assert len(selected) == 1, f"Expected 1 value, got {len(selected)}"
    print(f"   [OK] Found exact match: {selected[0].value_num}")

    # Test 2: Subset sum (100 + 150 = 250, or 50 + 200 = 250)
    print("\n2. Testing subset sum (target=250)...")
    selected, total = apv._select_values_without_change(values, 250)
    assert total == 250, f"Expected 250, got {total}"
    assert len(selected) == 2, f"Expected 2 values, got {len(selected)}"
    amounts = sorted([v.value_num for v in selected])
    assert sum(amounts) == 250, f"Expected sum 250, got {sum(amounts)}"
    print(f"   [OK] Found subset: {amounts}")

    # Test 3: Multiple values (50 + 100 + 150 = 300, or 300 = 300)
    print("\n3. Testing multiple values (target=300)...")
    selected, total = apv._select_values_without_change(values, 300)
    assert total == 300, f"Expected 300, got {total}"
    amounts = sorted([v.value_num for v in selected])
    assert sum(amounts) == 300, f"Expected sum 300, got {sum(amounts)}"
    print(f"   [OK] Found subset: {amounts}")

    # Test 4: No exact match (cannot make 123)
    print("\n4. Testing no exact match (cannot make 123)...")
    selected, total = apv._select_values_without_change(values, 123)
    assert total == 0, f"Expected 0 (no match), got {total}"
    assert len(selected) == 0, f"Expected 0 values, got {len(selected)}"
    print(f"   [OK] Correctly returns empty when no exact match possible")

    print("\n[PASS] All subset sum tests passed!")


def test_checkpoint_skip_logic():
    """Test that checkpoint values are skipped when they can't make exact amount"""
    print("\n" + "=" * 60)
    print("Test 2: Checkpoint Skip Logic")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Scenario: Checkpoint values are all too large (300, 400, 500)
    # Other values can make the exact amount (100, 150, 200)
    checkpoint_values = [
        Value("0xc001", 300, ValueState.UNSPENT),
        Value("0xc002", 400, ValueState.UNSPENT),
        Value("0xc003", 500, ValueState.UNSPENT),
    ]

    other_values = [
        Value("0x1000", 100, ValueState.UNSPENT),
        Value("0x2000", 150, ValueState.UNSPENT),
        Value("0x3000", 200, ValueState.UNSPENT),
    ]

    apv.add_values_from_list(checkpoint_values + other_values)

    # Test: Try to make 250 using checkpoint values first
    # Checkpoint values (all > 250) should be skipped, and other values should be used
    print("\n1. Testing checkpoint skip (target=250)...")
    print(f"   Checkpoint values: {[v.value_num for v in checkpoint_values]} (all > 250)")
    print(f"   Other values: {[v.value_num for v in other_values]}")

    selected, total = apv._select_values_without_change(checkpoint_values, 250)
    print(f"   Checkpoint attempt: total={total}, expected=0 (cannot make 250)")
    assert total == 0, f"Checkpoint should not be able to make 250"

    # Now try with other values
    selected, total = apv._select_values_without_change(other_values, 250)
    print(f"   Other values attempt: total={total}, expected=250")
    assert total == 250, f"Other values should make 250"
    amounts = sorted([v.value_num for v in selected])
    assert amounts == [100, 150], f"Expected [100, 150], got {amounts}"
    print(f"   [OK] Correctly used other values: {amounts}")

    print("\n[PASS] All checkpoint skip tests passed!")


def test_full_transaction_flow():
    """Test the full transaction flow with the fixes"""
    print("\n" + "=" * 60)
    print("Test 3: Full Transaction Flow")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Add values that can make various amounts exactly
    values = [
        Value("0x1000", 100, ValueState.UNSPENT),
        Value("0x2000", 200, ValueState.UNSPENT),
        Value("0x3000", 150, ValueState.UNSPENT),
        Value("0x3001", 50, ValueState.UNSPENT),
        Value("0x4000", 300, ValueState.UNSPENT),
    ]
    apv.add_values_from_list(values)

    # Test 1: Exact amount (200)
    print("\n1. Testing exact amount transaction (200)...")
    selected, main_tx = apv.pick_values_for_transaction(
        required_amount=200,
        sender=account_address,
        recipient="0xrecipient",
        nonce=1,
        time=1234567890
    )
    total = sum(v.value_num for v in selected)
    assert total == 200, f"Expected 200, got {total}"
    print(f"   [OK] Transaction created with exact amount: {total}")

    # Test 2: Subset sum amount (100 + 150 = 250, or 50 + 200 = 250)
    print("\n2. Testing subset sum transaction (target=250)...")
    selected, main_tx = apv.pick_values_for_transaction(
        required_amount=250,
        sender=account_address,
        recipient="0xrecipient",
        nonce=2,
        time=1234567890
    )
    total = sum(v.value_num for v in selected)
    assert total == 250, f"Expected 250, got {total}"
    amounts = sorted([v.value_num for v in selected])
    assert sum(amounts) == 250, f"Expected sum 250, got {sum(amounts)}"
    print(f"   [OK] Transaction created with subset: {amounts}")

    # Test 3: Impossible amount should raise error
    print("\n3. Testing impossible amount (should raise error)...")
    try:
        selected, main_tx = apv.pick_values_for_transaction(
            required_amount=123,
            sender=account_address,
            recipient="0xrecipient",
            nonce=3,
            time=1234567890
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"   [OK] Correctly raised error: {str(e)[:50]}...")

    print("\n[PASS] All full transaction flow tests passed!")


def test_edge_cases():
    """Test edge cases and boundary conditions"""
    print("\n" + "=" * 60)
    print("Test 4: Edge Cases and Boundary Conditions")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Test 1: Empty values list
    print("\n1. Testing empty values list...")
    selected, total = apv._select_values_without_change([], 100)
    assert total == 0, f"Expected 0, got {total}"
    assert len(selected) == 0, f"Expected empty list, got {len(selected)}"
    print("   [OK] Correctly handled empty list")

    # Test 2: Target amount is 0
    print("\n2. Testing target amount = 0...")
    values = [Value("0x1000", 100, ValueState.UNSPENT)]
    selected, total = apv._select_values_without_change(values, 0)
    assert total == 0, f"Expected 0, got {total}"
    assert len(selected) == 0, f"Expected empty list, got {len(selected)}"
    print("   [OK] Correctly handled target=0")

    # Test 3: Target amount is 1
    print("\n3. Testing target amount = 1...")
    values = [Value("0x1000", 1, ValueState.UNSPENT)]
    selected, total = apv._select_values_without_change(values, 1)
    assert total == 1, f"Expected 1, got {total}"
    assert len(selected) == 1, f"Expected 1 value, got {len(selected)}"
    print("   [OK] Correctly handled target=1")

    # Test 4: Single value exact match
    print("\n4. Testing single value exact match...")
    values = [Value("0x1000", 500, ValueState.UNSPENT)]
    selected, total = apv._select_values_without_change(values, 500)
    assert total == 500, f"Expected 500, got {total}"
    assert len(selected) == 1, f"Expected 1 value, got {len(selected)}"
    print("   [OK] Found exact match")

    # Test 5: Target larger than any single value but reachable
    print("\n5. Testing target larger than single value but reachable...")
    values = [
        Value("0x1000", 10, ValueState.UNSPENT),
        Value("0x2000", 20, ValueState.UNSPENT),
        Value("0x3000", 30, ValueState.UNSPENT),
    ]
    selected, total = apv._select_values_without_change(values, 60)
    assert total == 60, f"Expected 60, got {total}"
    assert sum(v.value_num for v in selected) == 60
    print("   [OK] Found combination for sum=60")

    # Test 6: Target equals sum of all values
    print("\n6. Testing target equals sum of all values...")
    selected, total = apv._select_values_without_change(values, 60)
    assert total == 60, f"Expected 60, got {total}"
    assert len(selected) == 3, f"Expected all 3 values, got {len(selected)}"
    print("   [OK] Used all values")

    # Test 7: Target larger than sum of all values (impossible)
    print("\n7. Testing target larger than sum (impossible)...")
    selected, total = apv._select_values_without_change(values, 100)
    assert total == 0, f"Expected 0 (impossible), got {total}"
    assert len(selected) == 0, f"Expected empty list, got {len(selected)}"
    print("   [OK] Correctly returned empty for impossible target")

    # Test 8: Target is between values (cannot make exact match)
    print("\n8. Testing target between values (cannot make exact match)...")
    values = [
        Value("0x1000", 10, ValueState.UNSPENT),
        Value("0x2000", 30, ValueState.UNSPENT),
    ]
    selected, total = apv._select_values_without_change(values, 15)
    assert total == 0, f"Expected 0, got {total}"
    print("   [OK] Correctly handled impossible amount")

    print("\n[PASS] All edge case tests passed!")


def test_duplicate_values():
    """Test handling of duplicate values"""
    print("\n" + "=" * 60)
    print("Test 5: Duplicate Values")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Test with duplicate values
    print("\n1. Testing duplicate values...")
    values = [
        Value("0x1000", 100, ValueState.UNSPENT),
        Value("0x2000", 100, ValueState.UNSPENT),  # Duplicate
        Value("0x3000", 100, ValueState.UNSPENT),  # Duplicate
        Value("0x4000", 200, ValueState.UNSPENT),
    ]

    # Should be able to make 200 using either two 100s or one 200
    selected, total = apv._select_values_without_change(values, 200)
    assert total == 200, f"Expected 200, got {total}"
    amounts = [v.value_num for v in selected]
    assert sum(amounts) == 200, f"Expected sum 200, got {sum(amounts)}"
    print(f"   [OK] Found combination: {amounts}")

    # Should be able to make 300 using three 100s
    selected, total = apv._select_values_without_change(values, 300)
    assert total == 300, f"Expected 300, got {total}"
    amounts = [v.value_num for v in selected]
    assert sum(amounts) == 300
    print(f"   [OK] Found combination: {amounts}")

    print("\n[PASS] All duplicate value tests passed!")


def test_large_scale():
    """Test with larger sets of values"""
    print("\n" + "=" * 60)
    print("Test 6: Large Scale Performance")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Test with 20 values
    print("\n1. Testing with 20 values...")
    import time
    values = []
    for i in range(20):
        values.append(Value(f"0x{i:04x}", (i + 1) * 10, ValueState.UNSPENT))

    start_time = time.time()
    selected, total = apv._select_values_without_change(values, 150)
    elapsed_time = (time.time() - start_time) * 1000  # Convert to ms

    assert total == 150, f"Expected 150, got {total}"
    print(f"   [OK] Found sum=150 in {elapsed_time:.2f}ms")
    print(f"   [OK] Used {len(selected)} values")

    # Test with 50 values (stress test)
    print("\n2. Testing with 50 values (stress test)...")
    values = []
    for i in range(50):
        values.append(Value(f"0x{i:04x}", (i + 1) * 5, ValueState.UNSPENT))

    start_time = time.time()
    selected, total = apv._select_values_without_change(values, 500)
    elapsed_time = (time.time() - start_time) * 1000

    assert total == 500, f"Expected 500, got {total}"
    print(f"   [OK] Found sum=500 in {elapsed_time:.2f}ms")
    print(f"   [OK] Used {len(selected)} values")

    # Test: impossible target with large set
    print("\n3. Testing impossible target with large set...")
    start_time = time.time()
    selected, total = apv._select_values_without_change(values, 99999)
    elapsed_time = (time.time() - start_time) * 1000

    assert total == 0, f"Expected 0 (impossible), got {total}"
    print(f"   [OK] Correctly returned empty in {elapsed_time:.2f}ms")

    print("\n[PASS] All large scale tests passed!")


def test_special_combinations():
    """Test special combination scenarios"""
    print("\n" + "=" * 60)
    print("Test 7: Special Combinations")
    print("=" * 60)

    account_address = "0xtest_account"
    collection = AccountValueCollection(account_address)
    apv = AccountPickValues(account_address, collection)

    # Test 1: Greedy would fail, but DP finds solution
    print("\n1. Testing case where greedy fails but DP succeeds...")
    values = [
        Value("0x1000", 1, ValueState.UNSPENT),
        Value("0x2000", 2, ValueState.UNSPENT),
        Value("0x3000", 5, ValueState.UNSPENT),
        Value("0x4000", 9, ValueState.UNSPENT),
    ]
    # Target 8: greedy would take 9 (too big), then fail. DP should find 1+2+5=8
    selected, total = apv._select_values_without_change(values, 8)
    assert total == 8, f"Expected 8, got {total}"
    amounts = sorted([v.value_num for v in selected])
    assert amounts == [1, 2, 5], f"Expected [1,2,5], got {amounts}"
    print(f"   [OK] Found combination: {amounts}")

    # Test 2: Multiple solutions exist
    print("\n2. Testing case with multiple valid solutions...")
    values = [
        Value("0x1000", 3, ValueState.UNSPENT),
        Value("0x2000", 5, ValueState.UNSPENT),
        Value("0x3000", 7, ValueState.UNSPENT),
        Value("0x4000", 8, ValueState.UNSPENT),
    ]
    # Target 8: could be 8 alone, or 3+5
    selected, total = apv._select_values_without_change(values, 8)
    assert total == 8, f"Expected 8, got {total}"
    amounts = sorted([v.value_num for v in selected])
    assert sum(amounts) == 8
    print(f"   [OK] Found one valid solution: {amounts}")

    # Test 3: All small values need to be combined
    print("\n3. Testing combination of many small values...")
    values = [Value(f"0x{i:04x}", 1, ValueState.UNSPENT) for i in range(10)]
    selected, total = apv._select_values_without_change(values, 10)
    assert total == 10, f"Expected 10, got {total}"
    assert len(selected) == 10, f"Expected 10 values, got {len(selected)}"
    print(f"   [OK] Combined all 10 values of amount 1")

    # Test 4: Large value + small values
    print("\n4. Testing large value + small values combination...")
    values = [
        Value("0x1000", 1000, ValueState.UNSPENT),
        Value("0x2000", 1, ValueState.UNSPENT),
        Value("0x3000", 2, ValueState.UNSPENT),
        Value("0x4000", 3, ValueState.UNSPENT),
    ]
    selected, total = apv._select_values_without_change(values, 1005)
    assert total == 1005, f"Expected 1005, got {total}"
    amounts = sorted([v.value_num for v in selected])
    assert amounts == [2, 3, 1000], f"Expected [2,3,1000], got {amounts}"
    print(f"   [OK] Found combination: {amounts}")

    print("\n[PASS] All special combination tests passed!")


def test_full_transaction_edge_cases():
    """Test full transaction with edge cases"""
    print("\n" + "=" * 60)
    print("Test 8: Full Transaction Edge Cases")
    print("=" * 60)

    # Test 1: Transaction with minimum amount
    print("\n1. Testing transaction with minimum amount (1)...")
    account_address1 = "0xtest_account_1"
    collection1 = AccountValueCollection(account_address1)
    apv1 = AccountPickValues(account_address1, collection1)
    values = [Value("0x1000", 1, ValueState.UNSPENT)]
    apv1.add_values_from_list(values)
    selected, main_tx = apv1.pick_values_for_transaction(
        required_amount=1,
        sender=account_address1,
        recipient="0xrecipient",
        nonce=1,
        time=1234567890
    )
    assert sum(v.value_num for v in selected) == 1
    print("   [OK] Transaction created with amount=1")

    # Test 2: Transaction with all values
    print("\n2. Testing transaction using all values...")
    account_address2 = "0xtest_account_2"
    collection2 = AccountValueCollection(account_address2)
    apv2 = AccountPickValues(account_address2, collection2)
    values = [
        Value("0x2000", 100, ValueState.UNSPENT),
        Value("0x3000", 200, ValueState.UNSPENT),
        Value("0x4000", 300, ValueState.UNSPENT),
    ]
    apv2.add_values_from_list(values)
    selected, main_tx = apv2.pick_values_for_transaction(
        required_amount=600,
        sender=account_address2,
        recipient="0xrecipient",
        nonce=2,
        time=1234567890
    )
    total = sum(v.value_num for v in selected)
    assert total == 600, f"Expected total 600, got {total}"
    # Note: DP may find any valid subset that sums to 600
    # In this case, the only way is to use all 3 values (100+200+300=600)
    amounts = sorted([v.value_num for v in selected])
    assert amounts == [100, 200, 300], f"Expected [100,200,300], got {amounts}"
    print(f"   [OK] Transaction created with total amount {total}")

    # Test 3: Impossible transaction should raise error
    print("\n3. Testing impossible transaction (should raise error)...")
    try:
        selected, main_tx = apv2.pick_values_for_transaction(
            required_amount=999,
            sender=account_address2,
            recipient="0xrecipient",
            nonce=3,
            time=1234567890
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"   [OK] Correctly raised error for impossible amount")

    print("\n[PASS] All full transaction edge case tests passed!")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Testing AccountPickValues Fixes (Enhanced)")
    print("=" * 60)

    try:
        test_subset_sum_algorithm()
        test_checkpoint_skip_logic()
        test_full_transaction_flow()
        test_edge_cases()
        test_duplicate_values()
        test_large_scale()
        test_special_combinations()
        test_full_transaction_edge_cases()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n[FAIL] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
