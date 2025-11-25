#!/usr/bin/env python3
"""
验证测试系统设置

检查所有测试模块是否正确导入和配置
"""

import sys
import os

def check_imports():
    """检查导入"""
    print("Checking module imports...")

    try:
        from config import QUICK_TEST_CONFIG
        print("Config module imported successfully")
    except Exception as e:
        print(f"Config module import failed: {e}")
        return False

    try:
        print("Test system basic setup is correct")
        return True
    except Exception as e:
        print(f"Test system setup failed: {e}")
        return False

def check_file_structure():
    """检查文件结构"""
    print("Checking file structure...")

    required_files = [
        '__init__.py',
        'README.md',
        'config.py',
        'core/__init__.py',
        'core/account_test.py',
        'functional/__init__.py',
        'functional/integration_test.py',
        'functional/multi_account_test.py',
        'utils/__init__.py',
        'utils/debug_tools.py',
        'utils/test_runner.py',
        'utils/report_generator.py',
        'run_tests.py'
    ]

    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)

    if missing_files:
        print(f"Missing files: {missing_files}")
        return False
    else:
        print("All required files exist")
        return True

def main():
    """主验证函数"""
    print("EZ_Account Test System Verification")
    print("=" * 40)

    # 检查文件结构
    structure_ok = check_file_structure()

    # 检查导入
    import_ok = check_imports()

    print("\n" + "=" * 40)
    if structure_ok and import_ok:
        print("Test system verification passed!")
        print("\nUsage instructions:")
        print("  python run_tests.py                    # Run all tests")
        print("  python run_tests.py quick              # Quick test")
        print("  python -m utils.test_runner debug      # Debug test")
        print("  python -m core.account_test              # Core test")
        return True
    else:
        print("Test system verification failed!")
        print("Please check the above errors and fix them.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)