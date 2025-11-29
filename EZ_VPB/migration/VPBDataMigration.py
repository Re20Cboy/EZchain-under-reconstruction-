"""
VPB数据迁移工具
用于处理AccountProofManager重构后的数据清理和迁移
"""

import os
import sqlite3
import sys
from typing import List, Dict, Any
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(__file__) + '/../..')

from proofs.ProofUnit import ProofUnit
from values.Value import Value


class VPBDataMigration:
    """
    VPB数据迁移类，负责处理AccountProofManager重构后的数据迁移工作
    """

    def __init__(self, account_address: str, db_path: str = "ez_account_proof_storage.db"):
        self.account_address = account_address
        self.db_path = db_path
        self.migration_log = []

    def log(self, message: str, level: str = "INFO"):
        """记录迁移日志"""
        log_entry = f"[{level}] {message}"
        self.migration_log.append(log_entry)
        print(log_entry)

    def check_legacy_schema(self) -> bool:
        """检查是否包含旧的schema（account_values表）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='account_values'
                """)
                result = cursor.fetchone()
                if result:
                    self.log("Found legacy account_values table", "INFO")
                    return True
                else:
                    self.log("No legacy schema found - already migrated", "INFO")
                    return False
        except Exception as e:
            self.log(f"Error checking legacy schema: {e}", "ERROR")
            return False

    def backup_database(self) -> bool:
        """备份数据库"""
        try:
            backup_path = f"{self.db_path}.backup_{int(os.path.getmtime(self.db_path)) if os.path.exists(self.db_path) else 'before_migration'}"
            if os.path.exists(self.db_path):
                import shutil
                shutil.copy2(self.db_path, backup_path)
                self.log(f"Database backed up to: {backup_path}", "INFO")
                return True
            else:
                self.log("Database file does not exist - no backup needed", "INFO")
                return True
        except Exception as e:
            self.log(f"Error backing up database: {e}", "ERROR")
            return False

    def migrate_legacy_value_data(self) -> bool:
        """迁移遗留的Value数据"""
        try:
            if not self.check_legacy_schema():
                return True  # 已经是最新schema，无需迁移

            with sqlite3.connect(self.db_path) as conn:
                # 获取所有遗留的Value数据
                cursor = conn.execute("""
                    SELECT value_id, value_data FROM account_values
                    WHERE account_address = ?
                """, (self.account_address,))

                legacy_values = cursor.fetchall()
                self.log(f"Found {len(legacy_values)} legacy values to migrate", "INFO")

                if not legacy_values:
                    return True

                # 统计信息
                total_proof_mappings = 0
                orphaned_mappings = 0

                # 检查每个Value的Proof映射情况
                for value_id, value_data in legacy_values:
                    # 检查是否有Proof映射
                    proof_cursor = conn.execute("""
                        SELECT COUNT(*) FROM account_value_proofs
                        WHERE account_address = ? AND value_id = ?
                    """, (self.account_address, value_id))

                    proof_count = proof_cursor.fetchone()[0]
                    total_proof_mappings += proof_count

                    if proof_count == 0:
                        orphaned_mappings += 1
                        self.log(f"Value {value_id} has no proof mappings", "WARNING")

                self.log(f"Total proof mappings found: {total_proof_mappings}", "INFO")
                self.log(f"Values with no proof mappings: {orphaned_mappings}", "INFO")

                # 验证Value数据的完整性
                corrupted_values = 0
                for value_id, value_data in legacy_values:
                    try:
                        value_dict = json.loads(value_data)
                        Value.from_dict(value_dict)  # 验证是否能正确反序列化
                    except Exception as e:
                        corrupted_values += 1
                        self.log(f"Corrupted value data for {value_id}: {e}", "ERROR")

                if corrupted_values > 0:
                    self.log(f"Found {corrupted_values} corrupted value records", "ERROR")
                    return False

                # 删除遗留的account_values表（因为Value数据现在由ValueCollection管理）
                conn.execute("DROP TABLE IF EXISTS account_values")
                conn.commit()

                self.log("Successfully migrated legacy value data", "INFO")
                self.log(f"- Processed {len(legacy_values)} value records")
                self.log(f"- Maintained {total_proof_mappings} proof mappings")
                self.log(f"- Removed orphaned account_values table")
                return True

        except Exception as e:
            self.log(f"Error migrating legacy value data: {e}", "ERROR")
            import traceback
            self.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            return False

    def validate_migration(self) -> bool:
        """验证迁移结果"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 检查遗留表是否已删除
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='account_values'
                """)
                if cursor.fetchone():
                    self.log("Legacy account_values table still exists", "ERROR")
                    return False

                # 验证Proof映射表完整性
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM account_value_proofs
                    WHERE account_address = ?
                """, (self.account_address,))

                mapping_count = cursor.fetchone()[0]
                self.log(f"Proof mappings preserved: {mapping_count}", "INFO")

                # 验证账户存在
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM accounts
                    WHERE account_address = ?
                """, (self.account_address,))

                account_exists = cursor.fetchone()[0] > 0
                if not account_exists and mapping_count > 0:
                    self.log("Account record missing but proof mappings exist", "ERROR")
                    return False

                self.log("Migration validation completed successfully", "INFO")
                return True

        except Exception as e:
            self.log(f"Error validating migration: {e}", "ERROR")
            return False

    def run_migration(self) -> bool:
        """运行完整的迁移流程"""
        self.log(f"Starting VPB data migration for account: {self.account_address}", "INFO")

        try:
            # 1. 备份数据库
            if not self.backup_database():
                self.log("Database backup failed - aborting migration", "ERROR")
                return False

            # 2. 检查遗留schema
            has_legacy = self.check_legacy_schema()
            if not has_legacy:
                self.log("No migration needed - schema is already up to date", "INFO")
                return True

            # 3. 执行迁移
            if not self.migrate_legacy_value_data():
                self.log("Value data migration failed", "ERROR")
                return False

            # 4. 验证迁移
            if not self.validate_migration():
                self.log("Migration validation failed", "ERROR")
                return False

            self.log("VPB data migration completed successfully", "INFO")
            return True

        except Exception as e:
            self.log(f"Migration failed with exception: {e}", "ERROR")
            import traceback
            self.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            return False

    def get_migration_summary(self) -> Dict[str, Any]:
        """获取迁移摘要"""
        return {
            'account_address': self.account_address,
            'database_path': self.db_path,
            'migration_completed': len([log for log in self.migration_log if 'completed successfully' in log.lower()]) > 0,
            'total_logs': len(self.migration_log),
            'error_count': len([log for log in self.migration_log if '[ERROR]' in log]),
            'warning_count': len([log for log in self.migration_log if '[WARNING]' in log]),
            'log_entries': self.migration_log
        }

    def save_migration_report(self, output_path: str = None) -> str:
        """保存迁移报告"""
        if not output_path:
            output_path = f"vpb_migration_report_{self.account_address}_{int(os.path.getmtime(__file__))}.json"

        try:
            report = self.get_migration_summary()
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            self.log(f"Migration report saved to: {output_path}", "INFO")
            return output_path

        except Exception as e:
            self.log(f"Error saving migration report: {e}", "ERROR")
            return ""


# 迁移工具的命令行接口
def main():
    """命令行迁移工具"""
    import argparse

    parser = argparse.ArgumentParser(description='VPB Data Migration Tool')
    parser.add_argument('account_address', help='Account address to migrate')
    parser.add_argument('--db-path', default='ez_account_proof_storage.db',
                       help='Path to the database file')
    parser.add_argument('--output', help='Output path for migration report')
    parser.add_argument('--dry-run', action='store_true',
                       help='Only check what would be migrated without making changes')

    args = parser.parse_args()

    # 创建迁移实例
    migration = VPBDataMigration(args.account_address, args.db_path)

    if args.dry_run:
        # 仅检查，不执行迁移
        print("=== DRY RUN MODE ===")
        has_legacy = migration.check_legacy_schema()
        if has_legacy:
            print("Legacy data found that would be migrated")
        else:
            print("No legacy data found - no migration needed")
        return

    # 执行迁移
    success = migration.run_migration()

    # 保存报告
    if args.output or True:  # 默认总是保存报告
        report_path = migration.save_migration_report(args.output)
        print(f"Migration report: {report_path}")

    # 退出码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()