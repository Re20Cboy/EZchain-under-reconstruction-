"""
调试工具

基于debug_account_test.py的集约化版本
提供Account和VPBManager的调试功能
"""

import sys
import os
import logging
from typing import Dict, Any, Optional, List

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
while project_root and os.path.basename(project_root) != 'real_EZchain':
    parent = os.path.dirname(project_root)
    if parent == project_root:  # 防止无限循环
        break
    project_root = parent
sys.path.insert(0, project_root)

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib

# 配置日志
logger = logging.getLogger(__name__)


class DebugTools:
    """调试工具类"""

    def __init__(self):
        self.debug_info = {}

    def generate_key_pair(self):
        """生成密钥对"""
        private_key = ec.generate_private_key(ec.SECP256K1(), default_backend())
        public_key = private_key.public_key()

        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_key_pem, public_key_pem

    def create_debug_account(self, name: str, balance: int = 1000) -> Optional[Account]:
        """创建调试账户"""
        try:
            private_key_pem, public_key_pem = self.generate_key_pair()
            address = f"debug_{name}_{hashlib.sha256(public_key_pem).hexdigest()[:12]}"

            account = Account(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=f"Debug_{name}"
            )

            # 初始化创世余额
            genesis_value = Value("0x1000", balance, ValueState.UNSPENT)
            genesis_proof_units = []
            genesis_block_index = BlockIndexList([0], owner=address)

            if account.initialize_from_genesis(genesis_value, genesis_proof_units, genesis_block_index):
                logger.info(f"调试账户 {name} 创建成功: {address}")
                return account
            else:
                logger.error(f"调试账户 {name} 初始化失败")
                return None

        except Exception as e:
            logger.error(f"创建调试账户 {name} 失败: {e}")
            return None

    def analyze_account_balance(self, account: Account) -> Dict[str, Any]:
        """分析账户余额问题"""
        analysis = {
            'account_name': account.name,
            'account_address': account.address,
            'value_collection_level': {},
            'vpb_manager_level': {},
            'account_level': {},
            'consistency_check': {}
        }

        try:
            # ValueCollection层级分析
            vc = account.vpb_manager.value_collection
            all_values = vc.get_all_values()
            unspent_values = vc.find_by_state(ValueState.UNSPENT)

            analysis['value_collection_level'] = {
                'total_values': len(all_values),
                'unspent_values': len(unspent_values),
                'total_balance': vc.get_total_balance(),
                'unspent_balance': vc.get_balance_by_state(ValueState.UNSPENT),
                'state_index': dict(vc._state_index)
            }

            # VPBManager层级分析
            vpb_unspent_values = account.vpb_manager.get_unspent_values()
            analysis['vpb_manager_level'] = {
                'get_all_values': len(account.vpb_manager.get_all_values()),
                'get_unspent_values': len(vpb_unspent_values),
                'get_unspent_balance': account.vpb_manager.get_unspent_balance(),
                'get_total_balance': account.vpb_manager.get_total_balance()
            }

            # Account层级分析
            analysis['account_level'] = {
                'get_available_balance': account.get_available_balance(),
                'get_total_balance': account.get_total_balance(),
                'get_values': len(account.get_values()),
                'get_unspent_values': len(account.get_unspent_values())
            }

            # 一致性检查
            vc_unspent_balance = analysis['value_collection_level']['unspent_balance']
            vpb_unspent_balance = analysis['vpb_manager_level']['get_unspent_balance']
            account_available_balance = analysis['account_level']['get_available_balance']

            analysis['consistency_check'] = {
                'vc_vs_vpb': vc_unspent_balance == vpb_unspent_balance,
                'vc_vs_account': vc_unspent_balance == account_available_balance,
                'expected_balance': vc_unspent_balance,
                'vc_balance': vc_unspent_balance,
                'vpb_balance': vpb_unspent_balance,
                'account_balance': account_available_balance
            }

            return analysis

        except Exception as e:
            analysis['error'] = str(e)
            logger.error(f"分析账户 {account.name} 失败: {e}")
            return analysis

    def print_balance_analysis(self, analysis: Dict[str, Any]):
        """打印余额分析结果"""
        print(f"\n=== 账户余额分析: {analysis['account_name']} ===")
        print(f"地址: {analysis['account_address']}")

        # ValueCollection层级
        vc = analysis['value_collection_level']
        print(f"\nValueCollection层级:")
        print(f"  总Value数: {vc['total_values']}")
        print(f"  未花销Value数: {vc['unspent_values']}")
        print(f"  总余额: {vc['total_balance']}")
        print(f"  未花销余额: {vc['unspent_balance']}")
        print(f"  状态索引: {vc['state_index']}")

        # VPBManager层级
        vpb = analysis['vpb_manager_level']
        print(f"\nVPBManager层级:")
        print(f"  get_all_values(): {vpb['get_all_values']}")
        print(f"  get_unspent_values(): {vpb['get_unspent_values']}")
        print(f"  get_unspent_balance(): {vpb['get_unspent_balance']}")
        print(f"  get_total_balance(): {vpb['get_total_balance']}")

        # Account层级
        acc = analysis['account_level']
        print(f"\nAccount层级:")
        print(f"  get_available_balance(): {acc['get_available_balance']}")
        print(f"  get_total_balance(): {acc['get_total_balance']}")
        print(f"  get_values(): {acc['get_values']}")
        print(f"  get_unspent_values(): {acc['get_unspent_values']}")

        # 一致性检查
        check = analysis['consistency_check']
        print(f"\n一致性检查:")
        print(f"  VC vs VPB: {'通过' if check['vc_vs_vpb'] else '失败'}")
        print(f"  VC vs Account: {'通过' if check['vc_vs_account'] else '失败'}")
        print(f"  期望余额: {check['expected_balance']}")
        print(f"  VC余额: {check['vc_balance']}")
        print(f"  VPB余额: {check['vpb_balance']}")
        print(f"  Account余额: {check['account_balance']}")

        if not check['vc_vs_vpb']:
            print("  发现VPBManager余额查询问题!")
        if not check['vc_vs_account']:
            print("  发现Account余额查询问题!")

    def debug_vpb_integrity(self, account: Account) -> Dict[str, Any]:
        """调试VPB完整性"""
        debug_result = {
            'account_name': account.name,
            'vpb_validation': account.validate_vpb_integrity(),
            'value_collection_validation': False,
            'state_consistency': {},
            'errors': []
        }

        try:
            # ValueCollection完整性验证
            vc = account.vpb_manager.value_collection
            debug_result['value_collection_validation'] = vc.validate_integrity()

            # 状态一致性验证
            all_values = vc.get_all_values()
            unspent_values = vc.find_by_state(ValueState.UNSPENT)

            debug_result['state_consistency'] = {
                'total_values': len(all_values),
                'unspent_values': len(unspent_values),
                'unspent_balance': sum(v.value_num for v in unspent_values),
                'total_balance': sum(v.value_num for v in all_values),
                'state_index_size': {state: len(node_ids) for state, node_ids in vc._state_index.items()}
            }

            # 详细Value状态检查
            value_states = {}
            for i, value in enumerate(all_values):
                value_states[f'value_{i}'] = {
                    'begin_index': value.begin_index,
                    'amount': value.value_num,
                    'state': value.state.value,
                    'is_unspent': value.state == ValueState.UNSPENT
                }
            debug_result['value_details'] = value_states

        except Exception as e:
            debug_result['errors'].append(f"VPB完整性调试失败: {e}")
            logger.error(f"调试VPB完整性失败: {e}")

        return debug_result

    def print_vpb_debug(self, debug_result: Dict[str, Any]):
        """打印VPB调试结果"""
        print(f"\n=== VPB完整性调试: {debug_result['account_name']} ===")
        print(f"VPB验证: {'通过' if debug_result['vpb_validation'] else '失败'}")
        print(f"ValueCollection验证: {'通过' if debug_result['value_collection_validation'] else '失败'}")

        state = debug_result['state_consistency']
        print(f"\n状态统计:")
        print(f"  总Value数: {state['total_values']}")
        print(f"  未花销Value数: {state['unspent_values']}")
        print(f"  未花销余额: {state['unspent_balance']}")
        print(f"  总余额: {state['total_balance']}")
        print(f"  状态索引大小: {state['state_index_size']}")

        if 'value_details' in debug_result:
            print(f"\nValue详情:")
            for value_key, value_info in debug_result['value_details'].items():
                status = "未花销" if value_info['is_unspent'] else "已花销"
                print(f"  {value_key}: {value_info['begin_index']}, "
                      f"金额={value_info['amount']}, "
                      f"状态={value_info['state']} {status}")

        if debug_result['errors']:
            print(f"\n错误:")
            for error in debug_result['errors']:
                print(f"  - {error}")

    def run_full_debug(self, name: str = "debug", balance: int = 1000) -> bool:
        """运行完整调试流程"""
        print(f"\n开始完整调试流程: {name}")

        try:
            # 创建调试账户
            account = self.create_debug_account(name, balance)
            if not account:
                print("创建调试账户失败")
                return False

            print(f"调试账户创建成功: {account.name}")

            # 余额分析
            balance_analysis = self.analyze_account_balance(account)
            self.print_balance_analysis(balance_analysis)

            # VPB完整性调试
            vpb_debug = self.debug_vpb_integrity(account)
            self.print_vpb_debug(vpb_debug)

            # 综合评估
            has_issues = (
                not balance_analysis['consistency_check']['vc_vs_vpb'] or
                not balance_analysis['consistency_check']['vc_vs_account'] or
                not vpb_debug['vpb_validation'] or
                not vpb_debug['value_collection_validation']
            )

            if has_issues:
                print(f"\n发现问题:")
                if not balance_analysis['consistency_check']['vc_vs_vpb']:
                    print("  - VPBManager余额查询问题")
                if not balance_analysis['consistency_check']['vc_vs_account']:
                    print("  - Account余额查询问题")
                if not vpb_debug['vpb_validation']:
                    print("  - VPB完整性验证失败")
                if not vpb_debug['value_collection_validation']:
                    print("  - ValueCollection完整性验证失败")
                return False
            else:
                print(f"\n调试完成，未发现问题")
                return True

        except Exception as e:
            print(f"调试流程失败: {e}")
            return False

        finally:
            # 清理
            if 'account' in locals() and account:
                try:
                    account.cleanup()
                except:
                    pass


# 便捷函数
def debug_account_balance(name: str = "debug", balance: int = 1000):
    """调试账户余额的便捷函数"""
    tools = DebugTools()
    return tools.analyze_account_balance(tools.create_debug_account(name, balance))


def debug_vpb_integrity(name: str = "debug", balance: int = 1000):
    """调试VPB完整性的便捷函数"""
    tools = DebugTools()
    account = tools.create_debug_account(name, balance)
    if account:
        return tools.debug_vpb_integrity(account)
    return None


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行调试
    tools = DebugTools()
    success = tools.run_full_debug("test_debug", 1000)

    exit(0 if success else 1)