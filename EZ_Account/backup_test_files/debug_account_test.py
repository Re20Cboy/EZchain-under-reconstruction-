#!/usr/bin/env python3
"""
调试Account和VPBManager的余额问题
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib


def debug_account_balance():
    """调试账户余额问题"""
    print("=== 调试Account和VPBManager的余额问题 ===")

    # 生成密钥对
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

    address = f"debug_account_{hashlib.sha256(public_key_pem).hexdigest()[:16]}"
    print(f"创建账户: {address}")

    # 创建Account对象
    account = Account(
        address=address,
        private_key_pem=private_key_pem,
        public_key_pem=public_key_pem,
        name="DebugAccount"
    )

    # 创建创世Value
    initial_balance = 1000
    genesis_value = Value("0x1000", initial_balance, ValueState.UNSPENT)
    print(f"创建创世Value: 金额={initial_balance}, 状态={genesis_value.state}")

    # 手动添加Value到ValueCollection进行调试
    print("\n=== 直接操作ValueCollection ===")
    value_collection = account.vpb_manager.value_collection

    print(f"添加前 - 总Value数: {len(value_collection.get_all_values())}")
    print(f"添加前 - 未花销Value数: {len(value_collection.find_by_state(ValueState.UNSPENT))}")
    print(f"添加前 - 总余额: {value_collection.get_total_balance()}")
    print(f"添加前 - 未花销余额: {value_collection.get_balance_by_state(ValueState.UNSPENT)}")

    # 直接添加Value
    success = value_collection.add_value(genesis_value)
    print(f"直接添加Value结果: {success}")

    print(f"添加后 - 总Value数: {len(value_collection.get_all_values())}")
    print(f"添加后 - 未花销Value数: {len(value_collection.find_by_state(ValueState.UNSPENT))}")
    print(f"添加后 - 总余额: {value_collection.get_total_balance()}")
    print(f"添加后 - 未花销余额: {value_collection.get_balance_by_state(ValueState.UNSPENT)}")

    # 检查添加的Value的状态
    all_values = value_collection.get_all_values()
    for i, value in enumerate(all_values):
        print(f"Value {i}: begin_index={value.begin_index}, amount={value.value_num}, state={value.state}")

    # 检查状态索引
    print(f"\n=== 状态索引调试 ===")
    print(f"UNSPENT状态索引: {value_collection._state_index.get(ValueState.UNSPENT)}")

    # 通过VPBManager初始化测试
    print("\n=== 通过VPBManager初始化测试 ===")

    # 创建新的Account用于VPBManager测试
    account2 = Account(
        address=f"debug_account_2_{hashlib.sha256(public_key_pem).hexdigest()[:16]}",
        private_key_pem=private_key_pem,
        public_key_pem=public_key_pem,
        name="DebugAccount2"
    )

    print(f"Account2初始化前:")
    print(f"  总Value数: {len(account2.vpb_manager.value_collection.get_all_values())}")
    print(f"  未花销Value数: {len(account2.vpb_manager.value_collection.find_by_state(ValueState.UNSPENT))}")
    print(f"  总余额: {account2.vpb_manager.value_collection.get_total_balance()}")
    print(f"  未花销余额: {account2.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)}")

    # 通过VPBManager初始化
    genesis_proof_units = []
    genesis_block_index = BlockIndexList([0], owner=account2.address)

    init_success = account2.initialize_from_genesis(genesis_value, genesis_proof_units, genesis_block_index)
    print(f"VPBManager初始化结果: {init_success}")

    print(f"Account2初始化后:")
    print(f"  总Value数: {len(account2.vpb_manager.value_collection.get_all_values())}")
    print(f"  未花销Value数: {len(account2.vpb_manager.value_collection.find_by_state(ValueState.UNSPENT))}")
    print(f"  总余额: {account2.vpb_manager.value_collection.get_total_balance()}")
    print(f"  未花销余额: {account2.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)}")
    print(f"  VPBManager.get_unspent_balance(): {account2.vpb_manager.get_unspent_balance()}")
    print(f"  VPBManager.get_total_balance(): {account2.vpb_manager.get_total_balance()}")

    # 检查VPB摘要
    vpb_summary = account2.get_vpb_summary()
    print(f"VPB摘要: {vpb_summary}")

    # 深度调试VPBManager方法
    print(f"\n=== VPBManager方法调试 ===")
    print(f"account2.vpb_manager.get_all_values(): {len(account2.vpb_manager.get_all_values())}")
    print(f"account2.vpb_manager.get_unspent_values(): {len(account2.vpb_manager.get_unspent_values())}")
    print(f"account2.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT): {account2.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)}")
    print(f"account2.vpb_manager.get_unspent_balance(): {account2.vpb_manager.get_unspent_balance()}")

    # 检查具体的unspent values
    unspent_values = account2.vpb_manager.get_unspent_values()
    print(f"  找到 {len(unspent_values)} 个未花销Value:")
    for i, value in enumerate(unspent_values):
        print(f"    Unspent Value {i}: begin_index={value.begin_index}, amount={value.value_num}, state={value.state}")

    # 检查所有values及其状态
    all_values = account2.vpb_manager.get_all_values()
    print(f"  总共有 {len(all_values)} 个Value:")
    for i, value in enumerate(all_values):
        print(f"    All Value {i}: begin_index={value.begin_index}, amount={value.value_num}, state={value.state}")
        print(f"      ValueState.UNSPENT比较: {value.state == ValueState.UNSPENT}")

    # 直接检查ValueCollection的状态索引
    print(f" ValueCollection状态索引:")
    print(f"    UNSPENT索引: {account2.vpb_manager.value_collection._state_index.get(ValueState.UNSPENT)}")
    print(f"    所有状态索引: {account2.vpb_manager.value_collection._state_index}")


if __name__ == "__main__":
    debug_account_balance()