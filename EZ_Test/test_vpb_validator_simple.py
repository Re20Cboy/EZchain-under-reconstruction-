#!/usr/bin/env python3
"""
VPB Validator 简化测试套件

专注于VPB验证的核心逻辑测试，避免复杂的数据结构验证。
"""

import pytest
import sys
import os
import tempfile
import time
from unittest.mock import Mock, MagicMock

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from EZ_VPB_Validator.vpb_validator import VPBValidator
    from EZ_VPB_Validator.core.types import (
        VerificationResult, VerificationError, VPBVerificationReport,
        MainChainInfo
    )
    from EZ_CheckPoint.CheckPoint import CheckPoint
    from EZ_VPB.values.Value import Value
except ImportError as e:
    print(f"导入模块错误: {e}")
    sys.exit(1)


class TestVPBValidatorCoreLogic:
    """测试VPB验证器的核心逻辑"""

    def test_validator_initialization(self):
        """测试验证器初始化"""
        # 无checkpoint的验证器
        validator = VPBValidator()
        assert validator.data_structure_validator is not None
        assert validator.slice_generator is not None
        assert validator.bloom_filter_validator is not None
        assert validator.proof_validator is not None

        # 带checkpoint的验证器
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator_with_cp = VPBValidator(checkpoint)
            assert validator_with_cp.slice_generator.checkpoint == checkpoint
            checkpoint = None
            time.sleep(0.1)
            try:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except PermissionError:
                pass

    def test_validator_statistics(self):
        """测试验证器统计功能"""
        validator = VPBValidator()

        # 初始统计
        stats = validator.get_verification_stats()
        assert stats['total'] == 0
        assert stats['successful'] == 0
        assert stats['failed'] == 0
        assert 'success_rate' in stats
        assert 'checkpoint_hit_rate' in stats

        # 重置统计
        validator.reset_stats()
        stats = validator.get_verification_stats()
        assert stats['total'] == 0

    def test_simple_verification_success(self):
        """测试简单的验证成功案例"""
        validator = VPBValidator()

        # 创建简化的测试数据
        value = Value("0x10000000000000000000000000000001", 100)

        # Mock所有组件以跳过实际验证
        validator.data_structure_validator.validate_basic_data_structure = Mock(return_value=(True, ""))
        validator.slice_generator.generate_vpb_slice = Mock(return_value=(Mock(), None))
        validator.bloom_filter_validator.verify_bloom_filter_consistency = Mock(return_value=(True, ""))
        validator.proof_validator.verify_proof_units_and_detect_double_spend = Mock(return_value=(True, [], []))

        main_chain = Mock(spec=MainChainInfo)

        report = validator.verify_vpb_pair(
            value, Mock(), Mock(), main_chain, "0xtest"
        )

        # 验证结果
        assert report.result == VerificationResult.SUCCESS
        assert report.is_valid == True
        assert len(report.errors) == 0
        assert report.verification_time_ms >= 0

    def test_simple_verification_failure_data_structure(self):
        """测试数据结构验证失败"""
        validator = VPBValidator()

        # Mock数据结构验证失败
        validator.data_structure_validator.validate_basic_data_structure = Mock(
            return_value=(False, "Data structure validation failed")
        )

        value = Value("0x10000000000000000000000000000001", 100)
        main_chain = Mock(spec=MainChainInfo)

        report = validator.verify_vpb_pair(
            value, Mock(), Mock(), main_chain, "0xtest"
        )

        # 验证结果
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) == 1
        assert report.errors[0].error_type == "DATA_STRUCTURE_VALIDATION_FAILED"

    def test_simple_verification_failure_bloom_filter(self):
        """测试布隆过滤器验证失败"""
        validator = VPBValidator()

        # Mock数据结构验证成功，但布隆过滤器验证失败
        validator.data_structure_validator.validate_basic_data_structure = Mock(return_value=(True, ""))
        validator.slice_generator.generate_vpb_slice = Mock(return_value=(Mock(), None))
        validator.bloom_filter_validator.verify_bloom_filter_consistency = Mock(
            return_value=(False, "Bloom filter validation failed")
        )
        validator.proof_validator.verify_proof_units_and_detect_double_spend = Mock(return_value=(True, [], []))

        value = Value("0x10000000000000000000000000000001", 100)
        main_chain = Mock(spec=MainChainInfo)

        report = validator.verify_vpb_pair(
            value, Mock(), Mock(), main_chain, "0xtest"
        )

        # 验证结果
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) >= 1
        assert any(err.error_type == "BLOOM_FILTER_VALIDATION_FAILED" for err in report.errors)

    def test_simple_verification_failure_proof_validation(self):
        """测试证明验证失败"""
        validator = VPBValidator()

        # Mock前面的验证成功，但证明验证失败
        validator.data_structure_validator.validate_basic_data_structure = Mock(return_value=(True, ""))
        validator.slice_generator.generate_vpb_slice = Mock(return_value=(Mock(), None))
        validator.bloom_filter_validator.verify_bloom_filter_consistency = Mock(return_value=(True, ""))

        proof_errors = [VerificationError("PROOF_VALIDATION_FAILED", "Proof validation failed")]
        validator.proof_validator.verify_proof_units_and_detect_double_spend = Mock(
            return_value=(False, proof_errors, [])
        )

        value = Value("0x10000000000000000000000000000001", 100)
        main_chain = Mock(spec=MainChainInfo)

        report = validator.verify_vpb_pair(
            value, Mock(), Mock(), main_chain, "0xtest"
        )

        # 验证结果
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) >= 1

    def test_checkpoint_usage(self):
        """测试checkpoint使用"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            checkpoint = CheckPoint(tmp.name)
            validator = VPBValidator(checkpoint)

            try:
                # 创建checkpoint
                value = Value("0x10000000000000000000000000000001", 100)
                checkpoint.create_checkpoint(value, "0xowner", 50)

                # Mock组件
                mock_slice = Mock()
                mock_checkpoint_record = Mock()
                mock_checkpoint_record.block_height = 50
                mock_checkpoint_record.owner_address = "0xowner"

                validator.data_structure_validator.validate_basic_data_structure = Mock(return_value=(True, ""))
                validator.slice_generator.generate_vpb_slice = Mock(return_value=(mock_slice, mock_checkpoint_record))
                validator.bloom_filter_validator.verify_bloom_filter_consistency = Mock(return_value=(True, ""))
                validator.proof_validator.verify_proof_units_and_detect_double_spend = Mock(return_value=(True, [], []))

                main_chain = Mock(spec=MainChainInfo)

                report = validator.verify_vpb_pair(
                    value, Mock(), Mock(), main_chain, "0xowner"
                )

                # 验证checkpoint被使用
                assert report.checkpoint_used is not None
                assert report.checkpoint_used.block_height == 50
                assert report.checkpoint_used.owner_address == "0xowner"

                # 验证统计更新
                stats = validator.get_verification_stats()
                assert stats['checkpoint_used'] > 0

            finally:
                checkpoint = None
                validator = None
                time.sleep(0.1)
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except PermissionError:
                    pass

    def test_exception_handling(self):
        """测试异常处理"""
        validator = VPBValidator()

        # Mock数据结构验证抛出异常
        validator.data_structure_validator.validate_basic_data_structure = Mock(
            side_effect=Exception("Test exception")
        )

        value = Value("0x10000000000000000000000000000001", 100)
        main_chain = Mock(spec=MainChainInfo)

        report = validator.verify_vpb_pair(
            value, Mock(), Mock(), main_chain, "0xtest"
        )

        # 验证异常被正确处理
        assert report.result == VerificationResult.FAILURE
        assert report.is_valid == False
        assert len(report.errors) == 1
        assert report.errors[0].error_type == "VERIFICATION_EXCEPTION"
        assert "Test exception" in report.errors[0].error_message

    def test_verification_time_measurement(self):
        """测试验证时间测量"""
        validator = VPBValidator()

        # Mock组件，添加一些延迟
        def mock_validate(*args, **kwargs):
            time.sleep(0.01)  # 10ms延迟
            return True, ""

        validator.data_structure_validator.validate_basic_data_structure = Mock(side_effect=mock_validate)
        validator.slice_generator.generate_vpb_slice = Mock(return_value=(Mock(), None))
        validator.bloom_filter_validator.verify_bloom_filter_consistency = Mock(return_value=(True, ""))
        validator.proof_validator.verify_proof_units_and_detect_double_spend = Mock(return_value=(True, [], []))

        value = Value("0x10000000000000000000000000000001", 100)
        main_chain = Mock(spec=MainChainInfo)

        start_time = time.time()
        report = validator.verify_vpb_pair(
            value, Mock(), Mock(), main_chain, "0xtest"
        )
        actual_time = time.time() - start_time

        # 验证时间被正确测量
        assert report.verification_time_ms > 0
        # 允许一些误差，但应该接近实际时间
        assert abs(report.verification_time_ms - actual_time * 1000) < 50  # 50ms误差范围


def run_simple_tests():
    """运行简化的测试"""
    print("=" * 60)
    print("VPB Validator 简化测试套件")
    print("=" * 60)

    test_class = TestVPBValidatorCoreLogic()
    test_methods = [
        ("验证器初始化测试", test_class.test_validator_initialization),
        ("验证器统计测试", test_class.test_validator_statistics),
        ("简单验证成功测试", test_class.test_simple_verification_success),
        ("数据结构验证失败测试", test_class.test_simple_verification_failure_data_structure),
        ("布隆过滤器验证失败测试", test_class.test_simple_verification_failure_bloom_filter),
        ("证明验证失败测试", test_class.test_simple_verification_failure_proof_validation),
        ("Checkpoint使用测试", test_class.test_checkpoint_usage),
        ("异常处理测试", test_class.test_exception_handling),
        ("验证时间测量测试", test_class.test_verification_time_measurement),
    ]

    passed = 0
    failed = 0

    for test_name, test_method in test_methods:
        print(f"\n运行 {test_name}...")
        try:
            test_method()
            print(f"[PASS] {test_name} - 通过")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test_name} - 失败: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    print(f"总计: {len(test_methods)} 个测试, 通过: {passed} 个, 失败: {failed} 个")
    print(f"成功率: {passed/len(test_methods)*100:.1f}%")
    print("=" * 60)

    return passed, failed


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "pytest":
            # 运行pytest测试
            pytest.main([__file__, "-v", "--tb=short"])
        elif command == "simple":
            # 运行简化测试
            run_simple_tests()
        else:
            print("未知命令。可用命令:")
            print("  pytest  - 运行pytest单元测试")
            print("  simple  - 运行简化测试")
    else:
        # 默认运行pytest
        print("运行VPB Validator简化pytest测试...")
        pytest.main([__file__, "-v"])

        print(f"\n要运行简化测试，请使用:")
        print(f"  python {__file__} simple")
        print("=" * 60)