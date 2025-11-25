"""
EZ_Account测试模块

这个模块包含了EZChain账户系统的所有测试代码，包括：
- 核心功能测试
- 集成测试
- 多账户测试
- 性能测试
- 调试工具

作者：Claude
日期：2025年1月
版本：1.0
"""

__version__ = "1.0.0"
__author__ = "Claude"

# 导入主要测试类
from .core.account_test import AccountTest
from .functional.integration_test import IntegrationTest
from .functional.multi_account_test import MultiAccountTest
from .utils.debug_tools import DebugTools

# 测试配置
from .config import (
    BaseTestConfig, AccountTestConfig, IntegrationTestConfig, MultiAccountTestConfig,
    QUICK_TEST_CONFIG, STANDARD_TEST_CONFIG, STRESS_TEST_CONFIG
)

__all__ = [
    'AccountTest',
    'IntegrationTest',
    'MultiAccountTest',
    'DebugTools',
    'BaseTestConfig',
    'AccountTestConfig',
    'IntegrationTestConfig',
    'MultiAccountTestConfig',
    'QUICK_TEST_CONFIG',
    'STANDARD_TEST_CONFIG',
    'STRESS_TEST_CONFIG'
]