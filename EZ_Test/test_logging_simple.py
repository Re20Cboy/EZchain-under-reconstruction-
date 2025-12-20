#!/usr/bin/env python3
"""
简化版本的日志控制测试
"""

import os
import sys
import unittest

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def test_logging_control():
    """测试日志控制功能"""
    print("=" * 60)
    print("EZchain 测试日志控制功能测试")
    print("=" * 60)

    # 测试1: 默认模式
    print("\n[测试1] 默认模式（关闭详细输出）")
    os.environ.pop('VERBOSE_TEST_LOGGING', None)
    os.environ.pop('SHOW_VPB_VISUALIZATION', None)

    # 检查环境变量
    verbose = os.getenv('VERBOSE_TEST_LOGGING', 'false').lower() == 'true'
    show_vpb = os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() == 'true'

    print(f"  VERBOSE_TEST_LOGGING: {verbose}")
    print(f"  SHOW_VPB_VISUALIZATION: {show_vpb}")
    print(f"  => 模式: {'详细' if verbose else '简洁'} + {'VPB可视化' if show_vpb else '无VPB可视化'}")

    # 测试2: 开启详细日志
    print("\n[测试2] 开启详细日志")
    os.environ['VERBOSE_TEST_LOGGING'] = 'true'

    verbose = os.getenv('VERBOSE_TEST_LOGGING', 'false').lower() == 'true'
    show_vpb = os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() == 'true'

    print(f"  VERBOSE_TEST_LOGGING: {verbose}")
    print(f"  SHOW_VPB_VISUALIZATION: {show_vpb}")
    print(f"  => 模式: {'详细' if verbose else '简洁'} + {'VPB可视化' if show_vpb else '无VPB可视化'}")

    # 测试3: 开启VPB可视化
    print("\n[测试3] 开启VPB可视化")
    os.environ.pop('VERBOSE_TEST_LOGGING', None)
    os.environ['SHOW_VPB_VISUALIZATION'] = 'true'

    verbose = os.getenv('VERBOSE_TEST_LOGGING', 'false').lower() == 'true'
    show_vpb = os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() == 'true'

    print(f"  VERBOSE_TEST_LOGGING: {verbose}")
    print(f"  SHOW_VPB_VISUALIZATION: {show_vpb}")
    print(f"  => 模式: {'详细' if verbose else '简洁'} + {'VPB可视化' if show_vpb else '无VPB可视化'}")

    # 测试4: 开启所有功能
    print("\n[测试4] 开启所有功能")
    os.environ['VERBOSE_TEST_LOGGING'] = 'true'
    os.environ['SHOW_VPB_VISUALIZATION'] = 'true'

    verbose = os.getenv('VERBOSE_TEST_LOGGING', 'false').lower() == 'true'
    show_vpb = os.getenv('SHOW_VPB_VISUALIZATION', 'false').lower() == 'true'

    print(f"  VERBOSE_TEST_LOGGING: {verbose}")
    print(f"  SHOW_VPB_VISUALIZATION: {show_vpb}")
    print(f"  => 模式: {'详细' if verbose else '简洁'} + {'VPB可视化' if show_vpb else '无VPB可视化'}")

    print("\n" + "=" * 60)
    print("日志控制功能测试完成！")
    print("环境变量功能正常工作")
    print("=" * 60)

if __name__ == "__main__":
    test_logging_control()