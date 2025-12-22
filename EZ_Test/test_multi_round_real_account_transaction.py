#!/usr/bin/env python3
"""
EZchain Multi-Round Blockchain Integration Tests with Real Account Nodes
使用真实Account节点的多轮区块链联调测试

基于test_blockchain_integration_with_real_account.py的单轮测试，
实现多轮连续交易测试，重复调用成熟的单轮测试方法。
注重日志输出的简洁、清晰性。
"""

import sys
import os
import unittest
import datetime
import json
import logging
import random
import copy
from typing import List, Dict, Any, Tuple

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

# 导入临时数据管理器
from temp_data_manager import TempDataManager, create_test_environment

# 导入单轮测试类，复用其成熟的方法
from test_blockchain_integration_with_real_account import TestBlockchainIntegrationWithRealAccount

# Configure logging - 多轮测试专用极简日志配置
logging.basicConfig(
    level=logging.CRITICAL,  # 只显示严重错误
    format='%(message)s',   # 最简化格式，只显示消息内容
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# 在多轮测试中，禁用几乎所有组件的日志输出
all_verbose_loggers = [
    'EZ_GENESIS', 'EZ_Main_Chain', 'EZ_Tx_Pool', 'EZ_Transaction',
    'EZ_Account', 'EZ_VPB_Validator', 'EZ_Miner', 'EZ_Tool_Box',
    'EZ_Units', 'SecureSignature', 'MultiTransactions', 'SingleTransaction',
    'TxPool', 'PickTx', 'AccountProofManager', 'AccountValueCollection',
    'VPBValidator', 'EpochExtractor', 'DataStructureValidator',
    'VPBSliceGenerator', 'BloomFilterValidator'
]

# 将所有可能的日志源都设为CRITICAL级别
for logger_name in all_verbose_loggers:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# 当前多轮测试模块也只保留必要的输出
current_logger = logging.getLogger(__name__)
current_logger.setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

import warnings
warnings.filterwarnings("ignore")


class TestMultiRoundBlockchainIntegration(unittest.TestCase):
    """使用真实Account节点的多轮区块链联调测试"""

    def setUp(self):
        """测试前准备：创建多轮测试环境"""
        print("\n" + "="*80)
        print("🚀 多轮交易测试环境初始化")
        print("="*80)

        # 创建临时数据管理器
        self.temp_manager = create_test_environment(
            test_name="multi_round_blockchain_integration",
            max_sessions=5
        )
        self.temp_manager.cleanup_old_sessions()
        self.temp_manager.create_session()

        # 验证临时目录创建成功
        session_dir = self.temp_manager.get_current_session_dir()
        print(f"📁 临时会话目录: {session_dir}")

        # 强制设置所有可能的logger为CRITICAL级别，确保多轮测试时最安静
        self._silence_all_loggers()

        # 创建单轮测试实例作为基础，复用其成熟的方法
        self.base_test = TestBlockchainIntegrationWithRealAccount()
        self.base_test.temp_manager = self.temp_manager  # 共享临时管理器

        # 调用单轮测试的setUp来初始化基础环境
        self.base_test.setUp()

        # 再次确保所有logger保持静默
        self._silence_all_loggers()

        # 继承基础设置
        self.accounts = self.base_test.accounts
        self.blockchain = self.base_test.blockchain
        self.transaction_pool = self.base_test.transaction_pool
        self.transaction_picker = self.base_test.transaction_picker
        self.miner_address = self.base_test.miner_address
        self.miner = self.base_test.miner
        # 注意：vpb_validator 已经不存在，每个Account都有自己的VPBValidator

        print(f"✅ 基础环境初始化完成")
        print(f"   - 账户数量: {len(self.accounts)}")
        print(f"   - 区块链状态: #{self.blockchain.get_latest_block_index()}")

    def _silence_all_loggers(self):
        """强制静默所有可能的日志输出"""
        # 禁用根logger
        logging.getLogger().setLevel(logging.CRITICAL)

        # 禁用所有已知的组件logger
        verbose_loggers = [
            'EZ_GENESIS', 'EZ_Main_Chain', 'EZ_Tx_Pool', 'EZ_Transaction',
            'EZ_Account', 'EZ_VPB_Validator', 'EZ_Miner', 'EZ_Tool_Box',
            'EZ_Units', 'SecureSignature', 'MultiTransactions', 'SingleTransaction',
            'TxPool', 'PickTx', 'AccountProofManager', 'AccountValueCollection',
            'VPBValidator', 'EpochExtractor', 'DataStructureValidator',
            'VPBSliceGenerator', 'BloomFilterValidator', 'Blockchain', 'Account'
        ]

        for logger_name in verbose_loggers:
            try:
                logging.getLogger(logger_name).setLevel(logging.CRITICAL)
            except:
                pass

        # 禁用当前测试模块的logger
        logger.setLevel(logging.CRITICAL)

    def tearDown(self):
        """测试后清理：清理多轮测试环境"""
        print("\n" + "="*80)
        print("🧹 多轮交易测试环境清理")
        print("="*80)

        try:
            # 调用基础测试的tearDown进行清理
            if hasattr(self, 'base_test'):
                self.base_test.tearDown()

            # 清理当前会话
            if hasattr(self, 'temp_manager') and self.temp_manager:
                self.temp_manager.cleanup_current_session()

            print("✅ 多轮测试环境清理完成")

        except Exception as e:
            print(f"❌ 多轮测试环境清理失败: {e}")
            logger.error(f"多轮测试环境清理失败: {e}")

        print("="*80)

    def print_round_header(self, round_num: int, total_rounds: int):
        """打印轮次标题"""
        print("\n" + "="*60)
        print(f"🔄 第 {round_num}/{total_rounds} 轮交易测试")
        print("="*60)

    def print_account_states(self, round_num: int, pre_round: bool = True):
        """打印账户状态摘要"""
        action = "轮次开始前" if pre_round else "轮次结束后"
        print(f"\n📊 {action}账户状态 (第{round_num}轮):")

        total_balance = 0
        total_available = 0

        for account in self.accounts:
            account_info = account.get_account_info()
            total_balance += account_info['balances']['total']
            total_available += account_info['balances']['available']

            status = ""
            if pre_round:
                # 轮次前显示可用余额
                status = f"可用: {account_info['balances']['available']}"
            else:
                # 轮次后显示余额变化
                status = f"总余额: {account_info['balances']['total']}"

            print(f"   💳 {account.name:8s}: {status}")

        print(f"   💰 系统总计 - 总余额: {total_balance}, 可用: {total_available}")

    def validate_system_integrity(self, round_num: int) -> bool:
        """验证系统完整性"""
        print(f"\n🔍 系统完整性验证 (第{round_num}轮后):")

        all_valid = True
        total_balance = 0
        total_available = 0

        for account in self.accounts:
            try:
                # 验证账户完整性
                integrity_valid = account.validate_integrity()

                if not integrity_valid:
                    print(f"   ❌ {account.name}: 完整性验证失败")
                    all_valid = False
                else:
                    account_info = account.get_account_info()
                    total_balance += account_info['balances']['total']
                    total_available += account_info['balances']['available']

                    # 简化状态显示
                    values_count = len(account.vpb_manager.get_all_values())
                    print(f"   ✅ {account.name:8s}: 总余额={account_info['balances']['total']:4d}, "
                          f"可用={account_info['balances']['available']:4d}, Values={values_count:2d}")

            except Exception as e:
                print(f"   💥 {account.name}: 验证异常 - {str(e)[:30]}")
                all_valid = False

        print(f"   📊 系统状态: 总余额={total_balance}, 可用={total_available}")

        if all_valid:
            print(f"   🎉 系统完整性验证通过")
        else:
            print(f"   ⚠️ 系统完整性验证发现问题")

        return all_valid

    def run_single_round_with_account_adjustments(self, round_num: int) -> Dict[str, Any]:
        """执行单轮交易，并对账户状态进行必要调整"""
        self.print_round_header(round_num, self.total_rounds)

        # 打印轮次开始前状态
        self.print_account_states(round_num, pre_round=True)

        # 记录轮次开始时的系统状态
        round_start_state = {}
        for account in self.accounts:
            account_info = account.get_account_info()
            round_start_state[account.name] = {
                'total_balance': account_info['balances']['total'],
                'available_balance': account_info['balances']['available']
            }

        try:
            # 执行单轮交易前再次确保日志静默
            self._silence_all_loggers()

            # 执行单轮交易 - 复用base_test的成熟方法
            print(f"\n⚡ 开始执行第 {round_num} 轮交易...")

            # 调用单轮测试的核心交易流程方法
            # 但需要调整一些参数以适应多轮测试
            self.base_test.test_complete_real_account_transaction_flow()

            print(f"✅ 第 {round_num} 轮交易执行完成")

            # 记录轮次结果
            round_result = {
                'round_num': round_num,
                'success': True,
                'start_state': round_start_state,
                'block_count': self.blockchain.get_latest_block_index(),
                'error': None
            }

        except Exception as e:
            print(f"❌ 第 {round_num} 轮交易执行失败: {e}")
            logger.error(f"第 {round_num} 轮交易执行失败: {e}")

            round_result = {
                'round_num': round_num,
                'success': False,
                'start_state': round_start_state,
                'block_count': self.blockchain.get_latest_block_index(),
                'error': str(e)
            }

        # 打印轮次结束后状态
        self.print_account_states(round_num, pre_round=False)

        # 验证系统完整性
        integrity_valid = self.validate_system_integrity(round_num)
        round_result['integrity_valid'] = integrity_valid

        return round_result

    def test_multi_round_transaction_flow(self, num_rounds: int = 3):
        """测试多轮完整交易流程"""
        self.total_rounds = num_rounds

        print(f"\n🎯 开始 {num_rounds} 轮完整交易流程测试")
        print(f"💡 每轮将执行: 创建→交易池→选择→区块→上链 的完整流程")

        # 记录多轮测试的初始状态
        initial_block_index = self.blockchain.get_latest_block_index()
        print(f"📊 初始区块链高度: #{initial_block_index}")

        # 存储每轮的结果
        round_results = []

        # 执行多轮交易
        for round_num in range(1, num_rounds + 1):
            round_result = self.run_single_round_with_account_adjustments(round_num)
            round_results.append(round_result)

            # 轮次间短暂暂停，便于观察
            if round_num < num_rounds:
                print(f"\n⏳ 等待 1 秒后开始下一轮...")
                import time
                time.sleep(1)

        # 多轮测试总结
        self.print_multi_round_summary(round_results, initial_block_index)

        # 验证多轮测试总体结果
        self.validate_multi_round_results(round_results)

    def print_multi_round_summary(self, round_results: List[Dict], initial_block_index: int):
        """打印多轮测试总结"""
        print("\n" + "="*80)
        print("📊 多轮交易测试总结")
        print("="*80)

        final_block_index = self.blockchain.get_latest_block_index()
        blocks_generated = final_block_index - initial_block_index

        successful_rounds = sum(1 for r in round_results if r['success'])
        integrity_valid_rounds = sum(1 for r in round_results if r.get('integrity_valid', False))

        print(f"🎯 测试轮数: {len(round_results)}")
        print(f"✅ 成功轮数: {successful_rounds}")
        print(f"🔗 生成区块: {blocks_generated}")
        print(f"🛡️ 完整性验证通过: {integrity_valid_rounds}")

        # 显示每轮简要结果
        print(f"\n📋 各轮结果摘要:")
        for result in round_results:
            status_icon = "✅" if result['success'] else "❌"
            integrity_icon = "🛡️" if result.get('integrity_valid', False) else "⚠️"
            block_count = result['block_count']

            print(f"   第{result['round_num']:2d}轮: {status_icon} 区块#{block_count:3d} {integrity_icon}")
            if result['error']:
                error_msg = result['error'][:40] + "..." if len(result['error']) > 40 else result['error']
                print(f"           错误: {error_msg}")

        # 最终系统状态
        print(f"\n💰 最终系统状态:")
        final_total_balance = 0
        for account in self.accounts:
            account_info = account.get_account_info()
            final_total_balance += account_info['balances']['total']
            print(f"   💳 {account.name}: 总余额={account_info['balances']['total']}, "
                  f"可用={account_info['balances']['available']}")

        print(f"   📊 系统总余额: {final_total_balance}")

    def validate_multi_round_results(self, round_results: List[Dict]):
        """验证多轮测试结果"""
        print(f"\n🔍 多轮测试结果验证:")

        # 基本断言
        self.assertGreater(len(round_results), 0, "应该有测试轮次")

        successful_rounds = sum(1 for r in round_results if r['success'])
        self.assertGreater(successful_rounds, 0, "至少应该有一轮成功")

        integrity_valid_rounds = sum(1 for r in round_results if r.get('integrity_valid', False))
        self.assertGreater(integrity_valid_rounds, 0, "至少应该有一轮完整性验证通过")

        # 验证每轮都生成了新的区块
        for i, result in enumerate(round_results):
            if i > 0 and result['success']:
                prev_block_count = round_results[i-1]['block_count']
                curr_block_count = result['block_count']
                self.assertGreater(curr_block_count, prev_block_count,
                                 f"第{result['round_num']}轮应该生成新区块")

        # 最终系统状态验证
        for account in self.accounts:
            integrity_valid = account.validate_integrity()
            self.assertTrue(integrity_valid, f"账户 {account.name} 最终完整性验证应该通过")

        print(f"   ✅ 所有验证通过")
        print(f"🎉 多轮交易测试验证成功！")


def run_multi_round_integration_tests(num_rounds: int = 3):
    """运行多轮集成测试"""

    # 设置编码以支持中文字符和emoji
    try:
        if sys.platform == "win32":
            # Windows下设置UTF-8编码
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            # 在Windows下设置环境变量以支持UTF-8
            os.environ['PYTHONIOENCODING'] = 'utf-8'
    except:
        pass

    print("=" * 80)
    print("🚀 EZchain 多轮真实Account节点集成测试")
    print(f"📈 计划执行 {num_rounds} 轮完整交易流程")
    print("💡 基于成熟的单轮测试方法，注重日志简洁性")
    print("=" * 80)

    # 创建测试套件
    suite = unittest.TestSuite()

    # 使用动态创建测试方法
    test_class = TestMultiRoundBlockchainIntegration

    # 动态添加测试方法
    def create_test_method(rounds):
        def test_method(self):
            self.test_multi_round_transaction_flow(rounds)
        return test_method

    # 添加测试方法
    test_method = create_test_method(num_rounds)
    test_method.__name__ = f"test_multi_round_with_{num_rounds}_rounds"
    setattr(test_class, test_method.__name__, test_method)

    suite.addTest(test_class(test_method.__name__))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    # 输出测试结果摘要
    print("\n" + "=" * 80)
    print("📊 多轮测试结果摘要")
    print("=" * 80)

    success_count = result.testsRun - len(result.failures) - len(result.errors)
    success_rate = (success_count / result.testsRun * 100) if result.testsRun > 0 else 0

    print(f"📈 运行测试: {result.testsRun}")
    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {len(result.failures)}")
    print(f"💥 错误: {len(result.errors)}")
    print(f"📊 成功率: {success_rate:.1f}%")

    if result.failures:
        print("\n❌ 失败的测试:")
        for test, traceback in result.failures:
            print(f"  • {test}")

    if result.errors:
        print("\n💥 错误的测试:")
        for test, traceback in result.errors:
            print(f"  • {test}")

    print("\n" + "=" * 80)
    if success_rate >= 100:
        print("🎉 多轮集成测试全部通过！系统运行稳定")
    elif success_rate >= 80:
        print("✅ 多轮集成测试基本通过，大部分功能正常")
    else:
        print("⚠️ 多轮集成测试存在问题，需要进一步调试")
    print("=" * 80)

    return result.wasSuccessful()


if __name__ == "__main__":
    import sys

    # 设置编码以支持中文字符和emoji
    try:
        if sys.platform == "win32":
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

    # 默认执行3轮测试，也可以通过命令行参数指定
    num_rounds = 3
    if len(sys.argv) > 1:
        try:
            num_rounds = int(sys.argv[1])
            num_rounds = max(1, min(10, num_rounds))  # 限制在1-10轮之间
        except ValueError:
            print(f"⚠️ 无效的轮数参数，使用默认值: {num_rounds}")

    success = run_multi_round_integration_tests(num_rounds)
    sys.exit(0 if success else 1)