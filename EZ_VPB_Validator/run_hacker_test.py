#!/usr/bin/env python3
"""
Hacker Test Runner

这个脚本用于正确运行黑客测试套件，避免相对导入问题。
使用方法：
  python run_hacker_test.py
"""

import sys
import os

def main():
    # 获取项目根目录
    project_root = os.path.dirname(os.path.abspath(__file__))

    # 确保项目根目录在Python路径中
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 设置PYTHONPATH环境变量
    os.environ['PYTHONPATH'] = project_root

    # 导入并运行测试
    try:
        from Test.test_bloom_filter_validator_hacker import run_hacker_test_suite
        results = run_hacker_test_suite()

        # 根据测试结果设置退出代码
        successful_attacks = sum(1 for _, result in results if result == 1)
        exit_code = 1 if successful_attacks > 0 else 0

        if exit_code == 0:
            print("\n✅ All security tests passed!")
        else:
            print(f"\n🚨 {successful_attacks} security vulnerabilities found!")

        return exit_code

    except ImportError as e:
        print(f"Import error: {e}")
        print("Please make sure you're running from the project root directory")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())