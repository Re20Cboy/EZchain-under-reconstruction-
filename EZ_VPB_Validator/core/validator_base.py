"""
VPB Validator Base Class

This module provides the base class and common utilities for VPB validation.
"""

import threading
import logging
from typing import Dict, Any, Optional


class ValidatorBase:
    """验证器基类，提供通用功能"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初始化验证器基类

        Args:
            logger: 日志记录器实例
        """
        self.logger = logger or self._create_default_logger()
        self._lock = threading.RLock()

    def _create_default_logger(self) -> logging.Logger:
        """创建默认日志记录器"""
        logger = logging.getLogger(self.__class__.__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
        return logger

    def _check_bloom_filter(self, bloom_filter: Any, owner_address: str) -> bool:
        """检查布隆过滤器"""
        from EZ_Units.Bloom import BloomFilter

        if isinstance(bloom_filter, BloomFilter):
            return owner_address in bloom_filter
        elif isinstance(bloom_filter, dict):
            # 兼容旧的字典格式
            return bloom_filter.get(owner_address, False)
        else:
            # 其他格式，尝试直接检查
            try:
                return owner_address in bloom_filter
            except (TypeError, AttributeError):
                self.logger.warning(f"Unsupported bloom filter type: {type(bloom_filter)}")
                return False