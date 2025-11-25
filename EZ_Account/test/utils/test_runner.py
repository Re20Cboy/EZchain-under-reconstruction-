"""
测试运行器

统一的测试运行入口，支持运行不同类型的测试
"""

import sys
import os
import time
import argparse
import logging
from typing import Dict, Any, Optional

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
while project_root and os.path.basename(project_root) != 'real_EZchain':
    parent = os.path.dirname(project_root)
    if parent == project_root:  # 防止无限循环
        break
    project_root = parent
sys.path.insert(0, project_root)

# Add test directory to Python path for relative imports
test_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, test_dir)

from config import (
    QUICK_TEST_CONFIG, STANDARD_TEST_CONFIG, STRESS_TEST_CONFIG,
    BaseTestConfig, IntegrationTestConfig, MultiAccountTestConfig
)
from core.account_test import AccountTest
from functional.integration_test import IntegrationTest
from functional.multi_account_test import MultiAccountTest
from utils.debug_tools import DebugTools

# 配置日志
logger = logging.getLogger(__name__)


class TestRunner:
    """测试运行器"""

    def __init__(self):
        self.test_results = {}

    def run_account_test(self, config: BaseTestConfig) -> Dict[str, Any]:
        """运行Account核心测试"""
        logger.info("运行Account核心测试")

        test = AccountTest(
            temp_dir=config.temp_dir,
            cleanup=config.cleanup_temp
        )

        return test.run_basic_test_suite()

    def run_integration_test(self, config: IntegrationTestConfig) -> Dict[str, Any]:
        """运行集成测试"""
        logger.info("运行集成测试")

        test = IntegrationTest(
            temp_dir=config.temp_dir,
            cleanup=config.cleanup_temp
        )

        return test.run_integration_test(
            num_accounts=config.num_accounts,
            num_transactions=config.test_transactions
        ).__dict__

    def run_multi_account_test(self, config: MultiAccountTestConfig) -> Dict[str, Any]:
        """运行多账户测试"""
        logger.info("运行多账户测试")

        test = MultiAccountTest(
            temp_dir=config.temp_dir,
            cleanup=config.cleanup_temp
        )

        return test.run_multi_account_test(
            num_accounts=config.num_accounts,
            num_transactions=config.test_transactions,
            test_duration=config.test_duration,
            block_interval=config.block_interval
        ).__dict__

    def run_debug_test(self) -> Dict[str, Any]:
        """运行调试测试"""
        logger.info("运行调试测试")

        tools = DebugTools()
        success = tools.run_full_debug("debug_test", 1000)

        return {
            'debug_test_passed': success,
            'test_type': 'debug'
        }

    def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        logger.info("运行所有测试套件")

        all_results = {
            'quick_test': None,
            'standard_test': None,
            'debug_test': None,
            'overall_success': False,
            'total_errors': 0,
            'execution_time': 0
        }

        start_time = time.time()

        try:
            # 1. 快速测试
            logger.info("=== 快速测试 ===")
            all_results['quick_test'] = self.run_account_test(QUICK_TEST_CONFIG)

            # 2. 标准集成测试
            logger.info("=== 标准集成测试 ===")
            all_results['standard_test'] = self.run_integration_test(STANDARD_TEST_CONFIG)

            # 3. 调试测试
            logger.info("=== 调试测试 ===")
            all_results['debug_test'] = self.run_debug_test()

        except Exception as e:
            logger.error(f"运行测试套件失败: {e}")
            all_results['error'] = str(e)

        finally:
            all_results['execution_time'] = time.time() - start_time

            # 统计错误
            for test_name, result in all_results.items():
                if isinstance(result, dict) and 'errors' in result:
                    all_results['total_errors'] += len(result['errors'])

            # 判断总体成功
            all_results['overall_success'] = (
                all_results.get('quick_test', {}).get('accounts_created', 0) > 0 and
                all_results.get('standard_test', {}).get('success_rate', 0) >= 50 and
                all_results.get('debug_test', {}).get('debug_test_passed', False) and
                all_results['total_errors'] < 5
            )

        return all_results

    def print_test_summary(self, results: Dict[str, Any]):
        """打印测试总结"""
        print("\n" + "=" * 60)
        print("测试执行总结")
        print("=" * 60)
        print(f"执行时间: {results.get('execution_time', 0):.2f} 秒")
        print(f"总体结果: {'成功' if results.get('overall_success', False) else '失败'}")
        print(f"总错误数: {results.get('total_errors', 0)}")

        # 各测试结果
        test_names = {
            'quick_test': '快速测试',
            'standard_test': '标准集成测试',
            'debug_test': '调试测试'
        }

        for test_key, test_name in test_names.items():
            if test_key in results and results[test_key]:
                result = results[test_key]
                print(f"\n{test_name}:")

                if test_key == 'debug_test':
                    status = "通过" if result.get('debug_test_passed', False) else "失败"
                    print(f"  结果: {status}")
                else:
                    accounts_created = result.get('accounts_created', 0)
                    transactions_created = result.get('transactions_created', 0)
                    success_rate = result.get('success_rate', 0)
                    errors = result.get('errors', [])

                    print(f"  创建账户: {accounts_created}")
                    print(f"  创建交易: {transactions_created}")
                    print(f"  成功率: {success_rate:.1f}%")
                    print(f"  错误数: {len(errors)}")

        # 建议
        print(f"\n建议:")
        if results.get('overall_success', False):
            print("  所有测试通过，系统运行正常")
        else:
            if results.get('total_errors', 0) > 0:
                print("  存在错误，请查看详细日志进行排查")
            else:
                print("  部分测试未通过，建议检查相关功能")


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="EZChain Account测试运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
测试类型说明:
  account        - 运行Account核心功能测试
  integration    - 运行集成测试
  multi-account  - 运行多账户测试
  debug         - 运行调试测试
  all           - 运行所有测试

示例用法:
  python test_runner.py account
  python test_runner.py integration
  python test_runner.py --quick
  python test_runner.py --stress
        """
    )

    parser.add_argument(
        'test_type',
        nargs='?',
        choices=['account', 'integration', 'multi-account', 'debug', 'all'],
        default='all',
        help='要运行的测试类型（默认: all）'
    )

    parser.add_argument(
        '--quick',
        action='store_true',
        help='运行快速测试'
    )

    parser.add_argument(
        '--stress',
        action='store_true',
        help='运行压力测试'
    )

    parser.add_argument(
        '--temp-dir',
        type=str,
        help='指定临时目录'
    )

    parser.add_argument(
        '--no-cleanup',
        action='store_true',
        help='测试后不清理临时文件'
    )

    args = parser.parse_args()

    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 创建测试运行器
    runner = TestRunner()

    try:
        if args.test_type == 'account':
            config = QUICK_TEST_CONFIG if args.quick else STANDARD_TEST_CONFIG
            config.temp_dir = args.temp_dir
            config.cleanup_temp = not args.no_cleanup
            results = runner.run_account_test(config)

        elif args.test_type == 'integration':
            config = QUICK_TEST_CONFIG if args.quick else (
                STRESS_TEST_CONFIG if args.stress else STANDARD_TEST_CONFIG
            )
            config.temp_dir = args.temp_dir
            config.cleanup_temp = not args.no_cleanup
            results = runner.run_integration_test(config)

        elif args.test_type == 'multi-account':
            config = QUICK_TEST_CONFIG if args.quick else (
                STRESS_TEST_CONFIG if args.stress else STANDARD_TEST_CONFIG
            )
            config.temp_dir = args.temp_dir
            config.cleanup_temp = not args.no_cleanup
            results = runner.run_multi_account_test(config)

        elif args.test_type == 'debug':
            results = runner.run_debug_test()

        elif args.test_type == 'all':
            results = runner.run_all_tests()

        else:
            raise ValueError(f"未知的测试类型: {args.test_type}")

        # 打印结果
        if isinstance(results, dict):
            runner.print_test_summary(results)

        # 设置退出码
        if (isinstance(results, dict) and
            results.get('overall_success', not isinstance(results, dict)) or
            (isinstance(results, dict) and 'debug_test_passed' in results and results['debug_test_passed'])):
            return 0
        else:
            return 1

    except KeyboardInterrupt:
        print("\n用户中断测试")
        return 130
    except Exception as e:
        logger.error(f"测试运行失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())