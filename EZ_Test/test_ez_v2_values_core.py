"""
EZchain-V2 值范围核心测试

设计文档对照：
- EZchain-V2-protocol-draft.md 第5节：值范围语义
- EZchain-V2 desgin-human-write.md：值守恒、切分、合并原则

测试类别：
- design-conformance: 验证值范围操作符合设计
- invariants: 验证值守恒不变量
- boundary: 验证边界条件
- negative: 验证非法操作被拒绝
"""

from __future__ import annotations

import unittest

from EZ_V2.values import (
    LocalValueStatus,
    LocalValueRecord,
    ValueRange,
)


class EZV2ValueRangeConstructionTests(unittest.TestCase):
    """
    [design-conformance] ValueRange构造测试
    """

    def test_value_range_with_valid_bounds(self) -> None:
        """验证ValueRange能用有效边界构造"""
        vr = ValueRange(0, 99)
        self.assertEqual(vr.begin, 0)
        self.assertEqual(vr.end, 99)
        self.assertEqual(vr.size, 100)

    def test_value_range_single_value(self) -> None:
        """验证ValueRange能表示单值"""
        vr = ValueRange(50, 50)
        self.assertEqual(vr.size, 1)
        self.assertTrue(vr.contains_value(50))

    def test_value_range_to_canonical_dict(self) -> None:
        """验证ValueRange能转换为canonical表示"""
        vr = ValueRange(10, 20)
        canonical = vr.to_canonical()
        self.assertEqual(canonical, {"begin": 10, "end": 20})


class EZV2ValueRangeNegativeTests(unittest.TestCase):
    """
    [negative] ValueRange拒绝非法输入测试
    """

    def test_value_range_rejects_negative_begin(self) -> None:
        """验证ValueRange拒绝负数begin"""
        with self.assertRaises(ValueError):
            ValueRange(-1, 10)

    def test_value_range_rejects_negative_end(self) -> None:
        """验证ValueRange拒绝负数end"""
        with self.assertRaises(ValueError):
            ValueRange(0, -1)

    def test_value_range_rejects_end_less_than_begin(self) -> None:
        """验证ValueRange拒绝end < begin"""
        with self.assertRaises(ValueError):
            ValueRange(10, 5)


class EZV2ValueRangeQueryTests(unittest.TestCase):
    """
    [design-conformance] ValueRange查询操作测试
    """

    def test_contains_value_true_for_value_in_range(self) -> None:
        """验证contains_value对范围内值返回True"""
        vr = ValueRange(10, 20)
        self.assertTrue(vr.contains_value(10))
        self.assertTrue(vr.contains_value(15))
        self.assertTrue(vr.contains_value(20))

    def test_contains_value_false_for_value_outside_range(self) -> None:
        """验证contains_value对范围外值返回False"""
        vr = ValueRange(10, 20)
        self.assertFalse(vr.contains_value(9))
        self.assertFalse(vr.contains_value(21))

    def test_intersects_true_for_overlapping_ranges(self) -> None:
        """验证intersects对重叠范围返回True"""
        vr1 = ValueRange(10, 20)
        vr2 = ValueRange(15, 25)
        self.assertTrue(vr1.intersects(vr2))
        self.assertTrue(vr2.intersects(vr1))

    def test_intersects_true_for_adjacent_ranges(self) -> None:
        """验证intersects对相邻范围返回True"""
        vr1 = ValueRange(10, 20)
        vr2 = ValueRange(20, 30)
        self.assertTrue(vr1.intersects(vr2))

    def test_intersects_false_for_disjoint_ranges(self) -> None:
        """验证intersects对不相交范围返回False"""
        vr1 = ValueRange(10, 20)
        vr2 = ValueRange(21, 30)
        self.assertFalse(vr1.intersects(vr2))

    def test_contains_range_true_for_subset(self) -> None:
        """验证contains_range对子集返回True"""
        vr1 = ValueRange(10, 50)
        vr2 = ValueRange(20, 30)
        self.assertTrue(vr1.contains_range(vr2))

    def test_contains_range_false_for_non_subset(self) -> None:
        """验证contains_range对非子集返回False"""
        vr1 = ValueRange(10, 30)
        vr2 = ValueRange(20, 50)
        self.assertFalse(vr1.contains_range(vr2))


class EZV2ValueRangeIntersectionTests(unittest.TestCase):
    """
    [design-conformance] ValueRange交集操作测试
    """

    def test_intersection_returns_overlap_for_overlapping_ranges(self) -> None:
        """验证intersection对重叠范围返回交集"""
        vr1 = ValueRange(10, 30)
        vr2 = ValueRange(20, 40)
        result = vr1.intersection(vr2)
        self.assertIsNotNone(result)
        self.assertEqual(result.begin, 20)
        self.assertEqual(result.end, 30)

    def test_intersection_returns_adjacent_value_for_adjacent_ranges(self) -> None:
        """验证intersection对相邻范围返回相邻值"""
        vr1 = ValueRange(10, 20)
        vr2 = ValueRange(20, 30)
        result = vr1.intersection(vr2)
        self.assertIsNotNone(result)
        self.assertEqual(result.begin, 20)
        self.assertEqual(result.end, 20)

    def test_intersection_returns_none_for_disjoint_ranges(self) -> None:
        """验证intersection对不相交范围返回None"""
        vr1 = ValueRange(10, 20)
        vr2 = ValueRange(21, 30)
        result = vr1.intersection(vr2)
        self.assertIsNone(result)


class EZV2ValueRangeSplitTests(unittest.TestCase):
    """
    [invariants] ValueRange切分测试

    验证值范围切分符合守恒定律：原范围 = 切分目标 + 剩余部分
    """

    def test_split_out_returns_target_and_remainders(self) -> None:
        """验证split_out返回目标和剩余部分"""
        original = ValueRange(0, 99)
        target = ValueRange(20, 39)

        extracted, remainders = original.split_out(target)

        # 验证提取的目标
        self.assertEqual(extracted.begin, 20)
        self.assertEqual(extracted.end, 39)

        # 验证剩余部分
        self.assertEqual(len(remainders), 2)
        self.assertEqual(remainders[0].begin, 0)
        self.assertEqual(remainders[0].end, 19)
        self.assertEqual(remainders[1].begin, 40)
        self.assertEqual(remainders[1].end, 99)

    def test_split_out_with_target_at_beginning(self) -> None:
        """验证从开头切分"""
        original = ValueRange(0, 99)
        target = ValueRange(0, 19)

        extracted, remainders = original.split_out(target)

        self.assertEqual(extracted, target)
        self.assertEqual(len(remainders), 1)
        self.assertEqual(remainders[0].begin, 20)
        self.assertEqual(remainders[0].end, 99)

    def test_split_out_with_target_at_end(self) -> None:
        """验证从末尾切分"""
        original = ValueRange(0, 99)
        target = ValueRange(80, 99)

        extracted, remainders = original.split_out(target)

        self.assertEqual(extracted, target)
        self.assertEqual(len(remainders), 1)
        self.assertEqual(remainders[0].begin, 0)
        self.assertEqual(remainders[0].end, 79)

    def test_split_out_with_exact_match(self) -> None:
        """验证完全匹配切分"""
        original = ValueRange(0, 99)
        target = ValueRange(0, 99)

        extracted, remainders = original.split_out(target)

        self.assertEqual(extracted, target)
        self.assertEqual(len(remainders), 0)

    def test_split_out_conservation_invariant(self) -> None:
        """验证切分守恒：所有部分的总和等于原范围"""
        original = ValueRange(10, 99)
        target = ValueRange(30, 49)

        extracted, remainders = original.split_out(target)

        # 重新组装所有部分
        all_parts = [extracted] + list(remainders)
        total_size = sum(part.size for part in all_parts)
        self.assertEqual(total_size, original.size)


class EZV2ValueRangeNegativeSplitTests(unittest.TestCase):
    """
    [negative] ValueRange切分负向测试
    """

    def test_split_out_rejects_target_not_contained(self) -> None:
        """验证split_out拒绝未被包含的目标"""
        original = ValueRange(10, 99)
        target = ValueRange(0, 9)  # 不在原范围内

        with self.assertRaises(ValueError):
            original.split_out(target)

    def test_split_out_rejects_target_partially_overlapping(self) -> None:
        """验证split_out拒绝部分重叠的目标"""
        original = ValueRange(50, 99)
        target = ValueRange(40, 60)  # 部分重叠

        with self.assertRaises(ValueError):
            original.split_out(target)


class EZV2LocalValueRecordTests(unittest.TestCase):
    """
    [design-conformance] LocalValueRecord测试
    """

    def test_local_value_record_construction(self) -> None:
        """验证LocalValueRecord能正确构造"""
        record = LocalValueRecord(
            record_id="test-record",
            value=ValueRange(0, 99),
            witness_v2={},  # 占位
            local_status=LocalValueStatus.VERIFIED_SPENDABLE,
            acquisition_height=1,
        )
        self.assertEqual(record.record_id, "test-record")
        self.assertEqual(record.local_status, LocalValueStatus.VERIFIED_SPENDABLE)

    def test_with_status_creates_new_record(self) -> None:
        """验证with_status创建新记录并修改状态"""
        original = LocalValueRecord(
            record_id="test-record",
            value=ValueRange(0, 99),
            witness_v2={},
            local_status=LocalValueStatus.PENDING_BUNDLE,
            acquisition_height=1,
        )

        updated = original.with_status(LocalValueStatus.ARCHIVED)

        # 验证新记录
        self.assertEqual(updated.local_status, LocalValueStatus.ARCHIVED)
        # 验证原记录不变
        self.assertEqual(original.local_status, LocalValueStatus.PENDING_BUNDLE)
        # 验证其他字段不变
        self.assertEqual(updated.record_id, original.record_id)
        self.assertEqual(updated.value, original.value)


class EZV2ValueStatusTransitionTests(unittest.TestCase):
    """
    [design-conformance] 值状态转换测试

    设计文档：protocol-draft.md 第12节
    验证值的状态转换符合设计规定的流程
    """

    def test_verified_spendable_to_pending_bundle_on_submit(self) -> None:
        """验证提交交易时VERIFIED_SPENDABLE转为PENDING_BUNDLE"""
        record = LocalValueRecord(
            record_id="test",
            value=ValueRange(0, 99),
            witness_v2={},
            local_status=LocalValueStatus.VERIFIED_SPENDABLE,
            acquisition_height=1,
        )

        # 模拟状态转换
        updated = record.with_status(LocalValueStatus.PENDING_BUNDLE)
        self.assertEqual(updated.local_status, LocalValueStatus.PENDING_BUNDLE)

    def test_pending_bundle_to_archived_on_confirmation(self) -> None:
        """验证确认后PENDING_BUNDLE转为ARCHIVED"""
        record = LocalValueRecord(
            record_id="test",
            value=ValueRange(0, 99),
            witness_v2={},
            local_status=LocalValueStatus.PENDING_BUNDLE,
            acquisition_height=1,
        )

        updated = record.with_status(LocalValueStatus.ARCHIVED)
        self.assertEqual(updated.local_status, LocalValueStatus.ARCHIVED)

    def test_all_status_values_are_distinct(self) -> None:
        """验证所有状态值互不相同"""
        statuses = [
            LocalValueStatus.VERIFIED_SPENDABLE,
            LocalValueStatus.PENDING_BUNDLE,
            LocalValueStatus.PENDING_CONFIRMATION,
            LocalValueStatus.RECEIPT_PENDING,
            LocalValueStatus.RECEIPT_MISSING,
            LocalValueStatus.LOCKED_FOR_VERIFICATION,
            LocalValueStatus.ARCHIVED,
        ]

        # 验证所有状态值唯一
        status_values = [s.value for s in statuses]
        self.assertEqual(len(status_values), len(set(status_values)))


class EZV2ValueRangeCombinatoricsTests(unittest.TestCase):
    """
    [invariants] 值范围组合测试

    验证值范围的组合操作符合守恒定律
    """

    def test_split_and_reconstruct_preserves_total_value(self) -> None:
        """验证切分后重组保持总值"""
        original = ValueRange(0, 999)
        middle = ValueRange(300, 699)

        # 切分
        extracted, remainders = original.split_out(middle)

        # 重组所有部分的总大小
        reconstructed_size = extracted.size + sum(r.size for r in remainders)
        self.assertEqual(reconstructed_size, original.size)

    def test_multiple_splits_preserve_conservation(self) -> None:
        """验证多次切分仍保持守恒"""
        original = ValueRange(0, 999)

        # 第一次切分
        target1 = ValueRange(100, 299)
        extracted1, remainders1 = original.split_out(target1)

        # 从剩余中再切分
        if remainders1:
            target2 = ValueRange(500, 699)
            # 找到包含target2的remainder
            for i, rem in enumerate(remainders1):
                if rem.contains_range(target2):
                    extracted2, remainders2 = rem.split_out(target2)
                    # 验证所有部分总和
                    all_parts = [extracted1] + list(remainders1[:i]) + [extracted2] + list(remainders2) + list(remainders1[i+1:])
                    total_size = sum(p.size for p in all_parts)
                    self.assertEqual(total_size, original.size)
                    break


if __name__ == "__main__":
    unittest.main()
