"""
EZ_Account功能测试模块

包含集成测试、多账户测试等功能性测试。
"""

from .integration_test import IntegrationTest
from .multi_account_test import MultiAccountTest

__all__ = ['IntegrationTest', 'MultiAccountTest']