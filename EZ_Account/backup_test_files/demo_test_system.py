#!/usr/bin/env python3
"""
EZChain多账户集成测试系统演示

这个脚本演示了如何使用多账户集成测试系统的各个组件。

作者：Claude
日期：2025年1月
"""

import sys
import os
import time
from typing import Dict, Any

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multi_account_integration_test import (
    TestConfig, TestStats, run_multi_account_integration_test
)
from test_analyzer import TestAnalyzer


def demo_test_configurations():
    """演示不同的测试配置"""
    print("🔧 测试配置演示")
    print("=" * 50)

    # 快速测试配置
    quick_config = TestConfig(
        num_accounts=2,
        num_transaction_rounds=3,
        transactions_per_round=2,
        block_interval=1.0,
        transaction_interval=0.3,
        test_duration=10,
        base_balance=1000,
        transaction_amount_range=(10, 100)
    )

    print("📋 快速测试配置:")
    print(f"  账户数量: {quick_config.num_accounts}")
    print(f"  测试时长: {quick_config.test_duration}秒")
    print(f"  初始余额: {quick_config.base_balance}")
    print(f"  交易金额范围: {quick_config.transaction_amount_range}")
    print()

    # 压力测试配置
    stress_config = TestConfig(
        num_accounts=8,
        num_transaction_rounds=50,
        transactions_per_round=8,
        block_interval=0.5,
        transaction_interval=0.1,
        test_duration=60,
        base_balance=20000,
        transaction_amount_range=(1, 1000)
    )

    print("📋 压力测试配置:")
    print(f"  账户数量: {stress_config.num_accounts}")
    print(f"  测试时长: {stress_config.test_duration}秒")
    print(f"  初始余额: {stress_config.base_balance}")
    print(f"  交易金额范围: {stress_config.transaction_amount_range}")
    print()

    return quick_config, stress_config


def demo_test_analyzer():
    """演示测试结果分析器"""
    print("📊 测试分析器演示")
    print("=" * 50)

    # 创建示例数据
    config = TestConfig(
        num_accounts=3,
        test_duration=30,
        base_balance=5000
    )

    # 模拟测试统计数据
    stats = TestStats(
        total_transactions_created=25,
        total_transactions_confirmed=24,
        total_blocks_created=8,
        total_vpb_updates=20,
        errors=[],
        start_time=time.time() - 30,
        end_time=time.time()
    )

    # 创建分析器
    analyzer = TestAnalyzer()

    # 分析测试结果
    report = analyzer.analyze_test_results(config, stats)

    # 显示关键指标
    print("🚀 性能指标:")
    print(f"  交易吞吐量: {report.metrics.transaction_throughput:.2f} TPS")
    print(f"  区块生成率: {report.metrics.block_generation_rate:.2f} BPS")
    print(f"  交易成功率: {report.metrics.transaction_success_rate:.2f}%")
    print(f"  系统稳定性评分: {report.metrics.system_stability_score:.2f}/100")
    print()

    # 显示分析结果
    print("🔍 分析结果:")
    for aspect, result in report.analysis.items():
        print(f"  {aspect}: {result}")
    print()

    # 显示改进建议
    if report.recommendations:
        print("💡 改进建议:")
        for i, recommendation in enumerate(report.recommendations, 1):
            print(f"  {i}. {recommendation}")
        print()

    return report


def demo_quick_test():
    """演示快速测试运行"""
    print("🚀 快速测试演示")
    print("=" * 50)

    # 创建快速测试配置
    config = TestConfig(
        num_accounts=2,
        num_transaction_rounds=2,
        transactions_per_round=2,
        block_interval=2.0,
        transaction_interval=0.5,
        test_duration=15,
        base_balance=2000,
        transaction_amount_range=(10, 100)
    )

    print("⏱️  开始运行快速测试...")
    print(f"配置: {config.num_accounts}个账户，{config.test_duration}秒时长")
    print("按Ctrl+C可以随时中断测试")
    print()

    try:
        # 运行测试
        stats = run_multi_account_integration_test(config)

        # 显示基本结果
        print("📊 测试结果:")
        print(f"  创建交易数: {stats.total_transactions_created}")
        print(f"  确认交易数: {stats.total_transactions_confirmed}")
        print(f"  创建区块数: {stats.total_blocks_created}")
        print(f"  VPB更新数: {stats.total_vpb_updates}")
        print(f"  交易成功率: {stats.success_rate:.2f}%")

        if stats.errors:
            print(f"  错误数量: {len(stats.errors)}")
            for i, error in enumerate(stats.errors, 1):
                print(f"    {i}. {error}")

        # 分析结果
        analyzer = TestAnalyzer()
        report = analyzer.analyze_test_results(config, stats)

        # 保存报告
        analyzer.save_report(report)

        return stats

    except KeyboardInterrupt:
        print("\n🛑 用户中断测试")
        return None
    except Exception as e:
        print(f"❌ 测试运行异常: {e}")
        return None


def demo_comparison():
    """演示测试结果比较"""
    print("📈 测试结果比较演示")
    print("=" * 50)

    # 创建两个不同的配置
    config1 = TestConfig(num_accounts=2, test_duration=10, base_balance=1000)
    config2 = TestConfig(num_accounts=4, test_duration=10, base_balance=1000)

    # 创建两组模拟统计数据
    stats1 = TestStats(
        total_transactions_created=10,
        total_transactions_confirmed=9,
        total_blocks_created=5,
        total_vpb_updates=8,
        errors=["轻微延迟"],
        start_time=time.time() - 10,
        end_time=time.time()
    )

    stats2 = TestStats(
        total_transactions_created=20,
        total_transactions_confirmed=19,
        total_blocks_created=5,
        total_vpb_updates=18,
        errors=[],
        start_time=time.time() - 10,
        end_time=time.time()
    )

    # 分析两个测试
    analyzer = TestAnalyzer()
    report1 = analyzer.analyze_test_results(config1, stats1)
    report2 = analyzer.analyze_test_results(config2, stats2)

    # 比较结果
    comparison = analyzer.compare_reports(report1, report2)

    print("📊 比较结果:")
    print(f"  测试1: {comparison['report1_name']}")
    print(f"  测试2: {comparison['report2_name']}")
    print()

    print("📈 指标改进:")
    if comparison['improvement_areas']:
        for improvement in comparison['improvement_areas']:
            print(f"  ✅ {improvement}")
    else:
        print("  无明显改进")
    print()

    print("📉 指标回退:")
    if comparison['regression_areas']:
        for regression in comparison['regression_areas']:
            print(f"  ⚠️ {regression}")
    else:
        print("  无明显回退")
    print()


def main():
    """主演示函数"""
    print("🎯 EZChain多账户集成测试系统演示")
    print("=" * 60)
    print()

    # 演示1: 测试配置
    quick_config, stress_config = demo_test_configurations()

    input("按Enter键继续到分析器演示...")

    # 演示2: 测试分析器
    demo_report = demo_test_analyzer()

    input("按Enter键继续到快速测试演示...")

    # 演示3: 快速测试（可选）
    run_test = input("是否运行实际测试？(y/n): ").lower().strip()
    if run_test == 'y':
        demo_quick_test()
    else:
        print("⏭️  跳过实际测试，使用模拟数据演示比较")
        demo_comparison()

    print()
    print("🎉 演示完成！")
    print()
    print("📚 更多信息:")
    print("  - 查看README_MultiAccountTest.md了解完整使用说明")
    print("  - 使用run_multi_account_test.py运行不同模式的测试")
    print("  - 使用test_analyzer.py分析测试结果")
    print()
    print("🚀 现在可以开始使用完整的测试系统了！")


if __name__ == "__main__":
    main()