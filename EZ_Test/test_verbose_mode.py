#!/usr/bin/env python3
"""
测试详细模式的功能
"""

import os
import sys

# 设置环境变量开启详细日志
os.environ['VERBOSE_TEST_LOGGING'] = 'true'

# 导入并运行测试
from test_blockchain_integration_with_real_account import run_real_account_integration_tests

if __name__ == "__main__":
    run_real_account_integration_tests()