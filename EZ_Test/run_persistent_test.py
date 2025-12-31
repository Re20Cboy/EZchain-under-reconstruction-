#!/usr/bin/env python3
"""
持久化多轮测试启动器
方便的命令行接口
"""

import sys
import os

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

# 设置编码以支持中文字符和emoji
try:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.environ['PYTHONIOENCODING'] = 'utf-8'
except:
    pass

from test_persistent_multi_round import main

if __name__ == "__main__":
    # 显示使用说明
    if len(sys.argv) == 1:
        print("="*60)
        print("🚀 EZchain 持久化多轮交易测试")
        print("="*60)
        print("\n使用方法:")
        print("  python run_persistent_test.py [选项]")
        print("\n选项:")
        print("  --rounds N        设置目标轮次 (默认: 20)")
        print("  --reset           重置测试状态，从头开始")
        print("  --storage-dir DIR 设置存储目录 (默认: EZ_Test/persistent_test_data)")
        print("\n示例:")
        print("  python run_persistent_test.py")
        print("  python run_persistent_test.py --rounds 50")
        print("  python run_persistent_test.py --reset")
        print("  python run_persistent_test.py --rounds 100 --storage-dir my_test")
        print("\n特性:")
        print("  ✅ 支持中断后继续运行")
        print("  ✅ 自动保存测试进度")
        print("  ✅ 永久存储，不删除测试数据")
        print("  ✅ 可以多次运行，累积测试轮次")
        print("  ✅ 测试数据存储在 EZ_Test 目录，已加入 .gitignore")
        print("="*60)
        print("\n开始运行默认测试 (20轮)...")
        print("-"*60)

    main()
