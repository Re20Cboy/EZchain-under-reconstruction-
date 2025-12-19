#!/usr/bin/env python3
"""
测试数据清理脚本
用于清理项目中残留的测试数据库文件
"""

import os
import shutil
import glob
import argparse
import logging
from pathlib import Path
from typing import List

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestDataCleaner:
    """测试数据清理器"""

    def __init__(self, project_root: str = "."):
        """
        初始化清理器

        Args:
            project_root: 项目根目录
        """
        self.project_root = Path(project_root).resolve()

    def find_database_files(self) -> List[Path]:
        """查找项目中的数据库文件"""
        db_patterns = [
            "**/*.db",
            "**/ez_*_storage.db",
            "**/test_*.db",
            "**/simulation_pool_*.db"
        ]

        db_files = []
        for pattern in db_patterns:
            # 使用glob查找匹配的文件
            files = list(self.project_root.glob(pattern))
            for file in files:
                if file.is_file():
                    db_files.append(file)

        return db_files

    def find_temp_directories(self) -> List[Path]:
        """查找临时测试目录"""
        temp_patterns = [
            "EZ_simulation_data",
            "temp_*",
            "test_*_data"
        ]

        temp_dirs = []
        for pattern in temp_patterns:
            dirs = list(self.project_root.glob(pattern))
            for dir_path in dirs:
                if dir_path.is_dir():
                    temp_dirs.append(dir_path)

        return temp_dirs

    def clean_database_files(self, dry_run: bool = False) -> List[Path]:
        """
        清理数据库文件

        Args:
            dry_run: 是否只是预览而不实际删除

        Returns:
            List[Path]: 被删除的文件列表
        """
        db_files = self.find_database_files()

        # 过滤掉不应该删除的文件
        excluded_patterns = [
            "node_modules",
            ".git",
            "backup_*",
            "__pycache__"
        ]

        files_to_delete = []
        for file in db_files:
            # 检查文件是否在排除目录中
            should_exclude = False
            for pattern in excluded_patterns:
                if pattern in str(file):
                    should_exclude = True
                    break

            if not should_exclude:
                files_to_delete.append(file)

        # 执行删除或预览
        deleted_files = []
        for file in files_to_delete:
            relative_path = file.relative_to(self.project_root)

            if dry_run:
                logger.info(f"[预览] 将删除: {relative_path}")
            else:
                try:
                    file.unlink()
                    logger.info(f"已删除: {relative_path}")
                    deleted_files.append(file)
                except Exception as e:
                    logger.error(f"删除失败 {relative_path}: {e}")

        return deleted_files

    def clean_temp_directories(self, dry_run: bool = False) -> List[Path]:
        """
        清理临时测试目录

        Args:
            dry_run: 是否只是预览而不实际删除

        Returns:
            List[Path]: 被删除的目录列表
        """
        temp_dirs = self.find_temp_directories()

        # 过滤掉不应该删除的目录
        excluded_patterns = [
            "node_modules",
            ".git",
            "backup_*",
            "__pycache__"
        ]

        dirs_to_delete = []
        for dir_path in temp_dirs:
            # 检查目录是否在排除列表中
            should_exclude = False
            for pattern in excluded_patterns:
                if pattern in str(dir_path):
                    should_exclude = True
                    break

            # 保留 temp_test_data（这是我们规范化的测试数据目录）
            if dir_path.name == "temp_test_data":
                should_exclude = True

            if not should_exclude:
                dirs_to_delete.append(dir_path)

        # 执行删除或预览
        deleted_dirs = []
        for dir_path in dirs_to_delete:
            relative_path = dir_path.relative_to(self.project_root)

            if dry_run:
                logger.info(f"[预览] 将删除目录: {relative_path}")
            else:
                try:
                    shutil.rmtree(dir_path)
                    logger.info(f"已删除目录: {relative_path}")
                    deleted_dirs.append(dir_path)
                except Exception as e:
                    logger.error(f"删除目录失败 {relative_path}: {e}")

        return deleted_dirs

    def clean_all(self, dry_run: bool = False):
        """清理所有测试数据"""
        logger.info("=" * 60)
        logger.info("开始清理测试数据...")
        if dry_run:
            logger.info("🔍 预览模式 - 不会实际删除文件")
        logger.info("=" * 60)

        # 清理数据库文件
        logger.info("\n🗃️ 清理数据库文件...")
        deleted_files = self.clean_database_files(dry_run)

        # 清理临时目录
        logger.info("\n📁 清理临时目录...")
        deleted_dirs = self.clean_temp_directories(dry_run)

        # 输出统计信息
        logger.info("\n" + "=" * 60)
        logger.info("📊 清理统计:")
        logger.info(f"   数据库文件: {'预览删除' if dry_run else '已删除'} {len(deleted_files)} 个")
        logger.info(f"   临时目录: {'预览删除' if dry_run else '已删除'} {len(deleted_dirs)} 个")

        if not dry_run:
            logger.info("\n✅ 测试数据清理完成！")
        else:
            logger.info("\n🔍 预览完成！使用 --execute 参数来执行实际删除")

        logger.info("=" * 60)

        return len(deleted_files), len(deleted_dirs)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="清理项目中的测试数据文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python cleanup_test_data.py --preview    # 预览要删除的文件
  python cleanup_test_data.py --execute    # 执行实际删除
  python cleanup_test_data.py --dry-run    # 同 --preview
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--preview", "--dry-run",
        action="store_true",
        help="预览要删除的文件，不实际删除"
    )
    group.add_argument(
        "--execute",
        action="store_true",
        help="执行实际删除"
    )

    args = parser.parse_args()

    # 创建清理器
    cleaner = TestDataCleaner()

    # 执行清理
    dry_run = args.preview
    cleaner.clean_all(dry_run=dry_run)


if __name__ == "__main__":
    main()