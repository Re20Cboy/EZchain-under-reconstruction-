#!/usr/bin/env python3
"""
测试日志控制开关的功能
"""

import os
import sys

def test_logging_control():
    """测试不同的日志控制设置"""
    print("=" * 60)
    print("🧪 测试日志控制开关功能")
    print("=" * 60)

    # 测试场景1: 默认设置（简洁模式）
    print("\n📋 场景1: 默认设置（简洁模式）")
    os.environ.pop('VERBOSE_TEST_LOGGING', None)
    os.environ.pop('SHOW_VPB_VISUALIZATION', None)

    # 导入并运行测试
    os.system("python test_blockchain_integration_with_real_account.py")

    print("\n" + "="*60)

    # 测试场景2: 仅开启详细日志
    print("\n📋 场景2: 仅开启详细日志")
    os.environ['VERBOSE_TEST_LOGGING'] = 'true'
    os.environ.pop('SHOW_VPB_VISUALIZATION', None)

    # 导入并运行测试
    os.system("python test_blockchain_integration_with_real_account.py")

    print("\n" + "="*60)

    # 测试场景3: 仅开启VPB可视化
    print("\n📋 场景3: 仅开启VPB可视化")
    os.environ.pop('VERBOSE_TEST_LOGGING', None)
    os.environ['SHOW_VPB_VISUALIZATION'] = 'true'

    # 导入并运行测试
    os.system("python test_blockchain_integration_with_real_account.py")

    print("\n" + "="*60)

    # 测试场景4: 开启所有日志（最详细模式）
    print("\n📋 场景4: 开启所有日志（最详细模式）")
    os.environ['VERBOSE_TEST_LOGGING'] = 'true'
    os.environ['SHOW_VPB_VISUALIZATION'] = 'true'

    # 导入并运行测试
    os.system("python test_blockchain_integration_with_real_account.py")

if __name__ == "__main__":
    test_logging_control()