#!/usr/bin/env python3
"""
测试临时数据管理器
用于管理测试期间生成的临时数据库文件，确保每次测试都有独立的环境
"""

import os
import shutil
import tempfile
import datetime
import time
import glob
import logging
from typing import Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class TempDataManager:
    """测试临时数据管理器"""

    def __init__(self,
                 base_temp_dir: str = "temp_test_data",
                 test_name: str = "default_test",
                 max_sessions_to_keep: int = 3):
        """
        初始化临时数据管理器

        Args:
            base_temp_dir: 基础临时目录
            test_name: 测试名称
            max_sessions_to_keep: 保留的最大会话数量
        """
        self.base_temp_dir = Path(base_temp_dir)
        self.test_name = test_name
        self.max_sessions_to_keep = max_sessions_to_keep
        self.current_session_dir: Optional[Path] = None
        self.session_created = False

        # 确保基础临时目录存在
        self.base_temp_dir.mkdir(exist_ok=True)

    def create_session(self) -> str:
        """
        创建新的测试会话目录

        Returns:
            str: 会话目录路径
        """
        # 生成带时间戳的会话目录名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"session_{timestamp}"
        session_dir = self.base_temp_dir / self.test_name / session_name

        # 创建会话目录结构
        session_dir.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (session_dir / "blockchain_data").mkdir(exist_ok=True)
        (session_dir / "pool_db").mkdir(exist_ok=True)
        (session_dir / "logs").mkdir(exist_ok=True)
        (session_dir / "account_storage").mkdir(exist_ok=True)

        self.current_session_dir = session_dir
        self.session_created = True

        logger.info(f"创建测试会话目录: {session_dir}")
        return str(session_dir)

    def cleanup_old_sessions(self):
        """清理旧的测试会话，保留最近指定的数量"""
        try:
            test_dir = self.base_temp_dir / self.test_name
            if not test_dir.exists():
                return

            # 获取所有会话目录并按时间排序
            session_dirs = []
            for item in test_dir.iterdir():
                if item.is_dir() and item.name.startswith("session_"):
                    try:
                        # 从目录名解析时间戳
                        timestamp_str = item.name.replace("session_", "")
                        timestamp = datetime.datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        session_dirs.append((timestamp, item))
                    except ValueError:
                        # 如果时间戳格式不对，跳过
                        continue

            # 按时间戳排序（最新的在前）
            session_dirs.sort(key=lambda x: x[0], reverse=True)

            # 删除超过保留数量的旧会话
            for i, (timestamp, session_dir) in enumerate(session_dirs):
                if i >= self.max_sessions_to_keep:
                    try:
                        shutil.rmtree(session_dir)
                        logger.info(f"清理旧会话目录: {session_dir}")
                    except Exception as e:
                        logger.error(f"清理会话目录失败 {session_dir}: {e}")

        except Exception as e:
            logger.error(f"清理旧会话时出错: {e}")

    def get_current_session_dir(self) -> Optional[str]:
        """获取当前会话目录路径"""
        return str(self.current_session_dir) if self.current_session_dir else None

    def get_blockchain_data_dir(self) -> Optional[str]:
        """获取区块链数据存储目录"""
        if self.current_session_dir:
            return str(self.current_session_dir / "blockchain_data")
        return None

    def get_pool_db_path(self) -> Optional[str]:
        """获取交易池数据库路径"""
        if self.current_session_dir:
            return str(self.current_session_dir / "pool_db" / "test_pool.db")
        return None

    def get_account_storage_dir(self) -> Optional[str]:
        """获取账户存储目录"""
        if self.current_session_dir:
            return str(self.current_session_dir / "account_storage")
        return None

    def get_log_dir(self) -> Optional[str]:
        """获取日志目录"""
        if self.current_session_dir:
            return str(self.current_session_dir / "logs")
        return None

    def cleanup_current_session(self):
        """清理当前会话目录"""
        if self.current_session_dir and self.current_session_dir.exists():
            try:
                shutil.rmtree(self.current_session_dir)
                logger.info(f"清理当前会话目录: {self.current_session_dir}")
                self.current_session_dir = None
                self.session_created = False
            except Exception as e:
                logger.error(f"清理当前会话目录失败: {e}")

    def __enter__(self):
        """上下文管理器入口"""
        self.cleanup_old_sessions()  # 先清理旧会话
        self.create_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        # 清理当前会话
        if self.current_session_dir:
            session_dir = self.current_session_dir  # 保存引用用于验证
            self.cleanup_current_session()
            # 清理后设置为None，表示会话已结束
            self.current_session_dir = None

    @staticmethod
    def cleanup_all_test_data(base_temp_dir: str = "temp_test_data"):
        """清理所有测试数据（谨慎使用）"""
        try:
            base_dir = Path(base_temp_dir)
            if base_dir.exists():
                shutil.rmtree(base_dir)
                logger.info(f"清理所有测试数据: {base_temp_dir}")
        except Exception as e:
            logger.error(f"清理所有测试数据失败: {e}")


# 便捷函数
def create_test_environment(test_name: str, max_sessions: int = 3) -> TempDataManager:
    """创建测试环境的便捷函数"""
    return TempDataManager(
        base_temp_dir="temp_test_data",
        test_name=test_name,
        max_sessions_to_keep=max_sessions
    )


# 示例用法
if __name__ == "__main__":
    # 使用上下文管理器
    with create_test_environment("blockchain_integration_test") as temp_mgr:
        print(f"当前会话目录: {temp_mgr.get_current_session_dir()}")
        print(f"区块链数据目录: {temp_mgr.get_blockchain_data_dir()}")
        print(f"交易池数据库路径: {temp_mgr.get_pool_db_path()}")

        # 在这里进行测试...
        time.sleep(1)  # 模拟测试过程