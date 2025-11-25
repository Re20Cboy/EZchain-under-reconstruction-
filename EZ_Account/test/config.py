"""
EZ_Account测试配置

包含所有测试的配置参数和常量定义。
"""

from dataclasses import dataclass
from typing import Tuple
import os
import tempfile


@dataclass
class BaseTestConfig:
    """基础测试配置"""
    temp_dir: str = None  # 临时目录，None表示自动创建
    cleanup_temp: bool = True  # 测试后是否清理临时文件
    log_level: str = "INFO"  # 日志级别
    timeout: int = 30  # 默认超时时间（秒）


@dataclass
class AccountTestConfig(BaseTestConfig):
    """账户测试配置"""
    num_accounts: int = 3
    base_balance: int = 1000
    test_transactions: int = 5
    transaction_amount_range: Tuple[int, int] = (10, 200)


@dataclass
class IntegrationTestConfig(AccountTestConfig):
    """集成测试配置"""
    test_duration: int = 20  # 测试时长（秒）
    transaction_interval: float = 0.5  # 交易间隔（秒）
    vpb_operations: bool = True  # 是否测试VPB操作
    signature_verification: bool = True  # 是否验证签名


@dataclass
class MultiAccountTestConfig(IntegrationTestConfig):
    """多账户测试配置"""
    num_processes: int = 4  # 进程数量（1个共识 + N-1个账户）
    block_interval: float = 2.0  # 区块生成间隔（秒）
    use_multiprocessing: bool = True  # 是否使用多进程（False表示多线程）
    network_simulation: bool = True  # 是否模拟网络延迟


# 预定义测试配置
QUICK_TEST_CONFIG = AccountTestConfig(
    num_accounts=2,
    base_balance=500,
    test_transactions=3,
    transaction_amount_range=(10, 100)
)

STANDARD_TEST_CONFIG = IntegrationTestConfig(
    num_accounts=3,
    base_balance=1000,
    test_transactions=5,
    transaction_amount_range=(50, 200),
    test_duration=30
)

STRESS_TEST_CONFIG = MultiAccountTestConfig(
    num_accounts=5,
    base_balance=5000,
    test_transactions=20,
    transaction_amount_range=(10, 500),
    test_duration=120,
    block_interval=1.0,
    use_multiprocessing=True
)


def get_default_temp_dir() -> str:
    """获取默认临时目录"""
    return tempfile.mkdtemp(prefix="ezchain_test_")


def validate_config(config: BaseTestConfig) -> bool:
    """验证配置参数的有效性"""
    if isinstance(config, AccountTestConfig):
        if config.num_accounts < 1:
            raise ValueError("账户数量必须大于0")
        if config.base_balance <= 0:
            raise ValueError("初始余额必须大于0")
        if (config.transaction_amount_range[0] <= 0 or
            config.transaction_amount_range[1] <= 0 or
            config.transaction_amount_range[0] >= config.transaction_amount_range[1]):
            raise ValueError("交易金额范围无效")

    if isinstance(config, IntegrationTestConfig):
        if config.test_duration <= 0:
            raise ValueError("测试时长必须大于0")
        if config.transaction_interval <= 0:
            raise ValueError("交易间隔必须大于0")

    if isinstance(config, MultiAccountTestConfig):
        if config.num_processes < 2:
            raise ValueError("多账户测试至少需要2个进程")
        if config.block_interval <= 0:
            raise ValueError("区块间隔必须大于0")

    return True


# 默认配置
DEFAULT_CONFIG = IntegrationTestConfig()