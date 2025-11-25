#!/usr/bin/env python3
"""
EZ_Account测试主入口

这是运行EZChain账户系统测试的主要入口点。
提供简单易用的命令行界面。

使用方法:
    python run_tests.py                    # 运行所有测试
    python run_tests.py quick              # 快速测试
    python run_tests.py account            # 账户测试
    python run_tests.py integration        # 集成测试
    python run_tests.py debug              # 调试测试
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
while project_root and os.path.basename(project_root) != 'real_EZchain':
    parent = os.path.dirname(project_root)
    if parent == project_root:  # 防止无限循环
        break
    project_root = parent
sys.path.insert(0, project_root)

# 导入测试运行器
from utils.test_runner import main

if __name__ == "__main__":
    sys.exit(main())