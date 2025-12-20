#!/usr/bin/env python3
"""
测试VPB可视化模式的功能
"""

import os
import sys

# 设置环境变量开启VPB可视化
os.environ['SHOW_VPB_VISUALIZATION'] = 'true'

# 导入并运行测试
from test_blockchain_integration_with_real_account import run_real_account_integration_tests

if __name__ == "__main__":
    run_real_account_integration_tests()