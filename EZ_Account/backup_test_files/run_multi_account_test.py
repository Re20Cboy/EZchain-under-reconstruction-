#!/usr/bin/env python3
"""
EZChain多账户集成测试运行器

这个脚本提供了一个简化的接口来运行多账户集成测试，
支持自定义配置参数和测试模式。

使用方法:
    python run_multi_account_test.py [--quick] [--long] [--custom]
"""

import sys
import os
import argparse
from typing import Dict, Any

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multi_account_integration_test import (
    TestConfig, run_multi_account_integration_test, logger
)


def create_quick_test_config() -> TestConfig:
    """创建快速测试配置"""
    return TestConfig(
        num_accounts=2,
        num_transaction_rounds=3,
        transactions_per_round=2,
        block_interval=1.0,
        transaction_interval=0.3,
        test_duration=10,
        base_balance=1000,
        transaction_amount_range=(10, 100)
    )


def create_long_test_config() -> TestConfig:
    """创建长时间测试配置"""
    return TestConfig(
        num_accounts=5,
        num_transaction_rounds=50,
        transactions_per_round=5,
        block_interval=2.0,
        transaction_interval=0.5,
        test_duration=120,
        base_balance=10000,
        transaction_amount_range=(50, 500)
    )


def create_stress_test_config() -> TestConfig:
    """创建压力测试配置"""
    return TestConfig(
        num_accounts=10,
        num_transaction_rounds=100,
        transactions_per_round=10,
        block_interval=1.0,
        transaction_interval=0.1,
        test_duration=300,
        base_balance=50000,
        transaction_amount_range=(1, 1000)
    )


def create_custom_config(args) -> TestConfig:
    """创建自定义测试配置"""
    return TestConfig(
        num_accounts=args.accounts,
        num_transaction_rounds=args.rounds,
        transactions_per_round=args.tx_per_round,
        block_interval=args.block_interval,
        transaction_interval=args.tx_interval,
        test_duration=args.duration,
        base_balance=args.balance,
        transaction_amount_range=(args.min_amount, args.max_amount)
    )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="EZChain多账户集成测试运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
测试模式说明:
  --quick      快速测试模式（2个账户，10秒）
  --long       长时间测试模式（5个账户，2分钟）
  --stress     压力测试模式（10个账户，5分钟）
  --custom     自定义参数测试

示例用法:
  python run_multi_account_test.py --quick
  python run_multi_account_test.py --long
  python run_multi_account_test.py --custom --accounts 4 --duration 60
        """
    )

    # 测试模式选项
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--quick', action='store_true', help='快速测试模式')
    mode_group.add_argument('--long', action='store_true', help='长时间测试模式')
    mode_group.add_argument('--stress', action='store_true', help='压力测试模式')
    mode_group.add_argument('--custom', action='store_true', help='自定义参数测试')

    # 自定义参数选项
    parser.add_argument('--accounts', type=int, default=3, help='账户数量 (默认: 3)')
    parser.add_argument('--rounds', type=int, default=10, help='交易轮数 (默认: 10)')
    parser.add_argument('--tx-per-round', type=int, default=3, help='每轮交易数 (默认: 3)')
    parser.add_argument('--block-interval', type=float, default=2.0, help='区块间隔秒数 (默认: 2.0)')
    parser.add_argument('--tx-interval', type=float, default=0.5, help='交易间隔秒数 (默认: 0.5)')
    parser.add_argument('--duration', type=int, default=30, help='测试时长秒数 (默认: 30)')
    parser.add_argument('--balance', type=int, default=5000, help='初始余额 (默认: 5000)')
    parser.add_argument('--min-amount', type=int, default=50, help='最小交易金额 (默认: 50)')
    parser.add_argument('--max-amount', type=int, default=200, help='最大交易金额 (默认: 200)')
    parser.add_argument('--temp-dir', type=str, help='临时数据目录路径')

    args = parser.parse_args()

    try:
        # 选择配置
        if args.quick:
            config = create_quick_test_config()
            logger.info("🚀 运行快速测试模式...")
        elif args.long:
            config = create_long_test_config()
            logger.info("⏰ 运行长时间测试模式...")
        elif args.stress:
            config = create_stress_test_config()
            logger.info("💪 运行压力测试模式...")
        else:  # custom
            config = create_custom_config(args)
            logger.info("⚙️ 运行自定义测试模式...")

        # 设置临时目录
        if args.temp_dir:
            config.temp_dir = args.temp_dir

        # 显示配置信息
        logger.info("测试配置:")
        logger.info(f"  账户数量: {config.num_accounts}")
        logger.info(f"  交易轮数: {config.num_transaction_rounds}")
        logger.info(f"  每轮交易数: {config.transactions_per_round}")
        logger.info(f"  区块间隔: {config.block_interval}秒")
        logger.info(f"  交易间隔: {config.transaction_interval}秒")
        logger.info(f"  测试时长: {config.test_duration}秒")
        logger.info(f"  初始余额: {config.base_balance}")
        logger.info(f"  交易金额范围: {config.transaction_amount_range}")
        logger.info(f"  临时目录: {config.temp_dir}")

        # 运行测试
        stats = run_multi_account_integration_test(config)

        # 根据测试结果返回退出码
        if stats.success_rate >= 80 and len(stats.errors) == 0:
            logger.info("✅ 测试成功完成!")
            return 0
        else:
            logger.error("❌ 测试失败!")
            return 1

    except KeyboardInterrupt:
        logger.info("🛑 用户中断测试")
        return 130
    except Exception as e:
        logger.error(f"💥 测试运行异常: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())