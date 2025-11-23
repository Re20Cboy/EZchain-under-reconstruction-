"""
CheckPoint模块测试

测试EZchain CheckPoint功能的核心特性：
- 检查点创建和更新
- 检查点查询和验证
- 持久化存储
- 序列化和反序列化
"""

import pytest
import sys
import os
import tempfile
from datetime import datetime, timezone

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_CheckPoint.CheckPoint import CheckPoint, CheckPointRecord, CheckPointStorage
from EZ_VPB.values.Value import Value, ValueState


class TestCheckPointRecord:
    """测试CheckPointRecord数据结构"""

    def test_checkpoint_record_creation(self):
        """测试检查点记录创建"""
        record = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        assert record.value_begin_index == "0x1000"
        assert record.value_num == 100
        assert record.owner_address == "0x1234567890abcdef"
        assert record.block_height == 100
        assert record.value_end_index == "0x1063"  # 0x1000 + 100 - 1 = 4096 + 100 - 1 = 4195 = 0x1063

    def test_checkpoint_record_serialization(self):
        """测试检查点记录序列化"""
        now = datetime.now(timezone.utc)
        record = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=now,
            updated_at=now
        )

        # 测试to_dict
        data = record.to_dict()
        assert data['value_begin_index'] == "0x1000"
        assert data['value_num'] == 100
        assert data['owner_address'] == "0x1234567890abcdef"
        assert data['block_height'] == 100

        # 测试from_dict
        restored_record = CheckPointRecord.from_dict(data)
        assert restored_record.value_begin_index == record.value_begin_index
        assert restored_record.value_num == record.value_num
        assert restored_record.owner_address == record.owner_address
        assert restored_record.block_height == record.block_height

    def test_checkpoint_record_matches_value(self):
        """测试检查点记录与Value的匹配"""
        record = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # 创建匹配的Value
        matching_value = Value("0x1000", 100)
        assert record.matches_value(matching_value) == True

        # 创建不匹配的Value（不同的begin_index）
        non_matching_value1 = Value("0x2000", 100)
        assert record.matches_value(non_matching_value1) == False

        # 创建不匹配的Value（不同的value_num）
        non_matching_value2 = Value("0x1000", 200)
        assert record.matches_value(non_matching_value2) == False

    def test_checkpoint_record_contains_value(self):
        """测试检查点记录的包含关系"""
        record = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # 完全包含的Value
        contained_value1 = Value("0x1000", 50)  # 子集
        assert record.contains_value(contained_value1) == True

        contained_value2 = Value("0x1020", 30)  # 中间部分
        assert record.contains_value(contained_value2) == True

        contained_value3 = Value("0x1060", 3)   # 结尾部分
        assert record.contains_value(contained_value3) == True

        # 不包含的Value
        not_contained_value1 = Value("0x0F00", 50)  # 完全在外面
        assert record.contains_value(not_contained_value1) == False

        not_contained_value2 = Value("0x1000", 101)  # 超出范围
        assert record.contains_value(not_contained_value2) == False

        not_contained_value3 = Value("0x1064", 10)   # 部分超出
        assert record.contains_value(not_contained_value3) == False


class TestCheckPointStorage:
    """测试检查点存储功能"""

    @pytest.fixture
    def temp_storage(self):
        """创建临时存储实例"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        storage = CheckPointStorage(db_path)
        yield storage

        # 清理 - Windows需要先关闭连接
        storage = None
        import time
        time.sleep(0.1)
        try:
            if os.path.exists(db_path):
                os.unlink(db_path)
        except PermissionError:
            pass  # Windows有时无法立即删除文件

    def test_store_and_load_checkpoint(self, temp_storage):
        """测试存储和加载检查点"""
        now = datetime.now(timezone.utc)
        checkpoint = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=now,
            updated_at=now
        )

        # 存储检查点
        assert temp_storage.store_checkpoint(checkpoint) == True

        # 加载检查点
        loaded_checkpoint = temp_storage.load_checkpoint("0x1000", 100)
        assert loaded_checkpoint is not None
        assert loaded_checkpoint.value_begin_index == "0x1000"
        assert loaded_checkpoint.value_num == 100
        assert loaded_checkpoint.owner_address == "0x1234567890abcdef"
        assert loaded_checkpoint.block_height == 100

    def test_update_checkpoint(self, temp_storage):
        """测试更新检查点"""
        now = datetime.now(timezone.utc)
        original_checkpoint = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=now,
            updated_at=now
        )

        # 存储原始检查点
        assert temp_storage.store_checkpoint(original_checkpoint) == True

        # 创建更新后的检查点
        updated_time = datetime.now(timezone.utc)
        updated_checkpoint = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0xfedcba0987654321",
            block_height=150,
            created_at=now,
            updated_at=updated_time
        )

        # 存储更新的检查点
        assert temp_storage.store_checkpoint(updated_checkpoint) == True

        # 验证更新
        loaded_checkpoint = temp_storage.load_checkpoint("0x1000", 100)
        assert loaded_checkpoint.owner_address == "0xfedcba0987654321"
        assert loaded_checkpoint.block_height == 150

    def test_delete_checkpoint(self, temp_storage):
        """测试删除检查点"""
        now = datetime.now(timezone.utc)
        checkpoint = CheckPointRecord(
            value_begin_index="0x1000",
            value_num=100,
            owner_address="0x1234567890abcdef",
            block_height=100,
            created_at=now,
            updated_at=now
        )

        # 存储检查点
        assert temp_storage.store_checkpoint(checkpoint) == True

        # 验证存在
        loaded_checkpoint = temp_storage.load_checkpoint("0x1000", 100)
        assert loaded_checkpoint is not None

        # 删除检查点
        assert temp_storage.delete_checkpoint("0x1000", 100) == True

        # 验证已删除
        loaded_checkpoint = temp_storage.load_checkpoint("0x1000", 100)
        assert loaded_checkpoint is None


class TestCheckPoint:
    """测试CheckPoint管理器"""

    @pytest.fixture
    def temp_checkpoint(self):
        """创建临时CheckPoint实例"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        checkpoint = CheckPoint(db_path)
        yield checkpoint

        # 清理 - Windows需要先关闭连接
        checkpoint = None
        import time
        time.sleep(0.1)
        try:
            if os.path.exists(db_path):
                os.unlink(db_path)
        except PermissionError:
            pass  # Windows有时无法立即删除文件

    @pytest.fixture
    def sample_value(self):
        """创建示例Value对象"""
        return Value("0x1000", 100)

    def test_create_checkpoint(self, temp_checkpoint, sample_value):
        """测试创建检查点"""
        success = temp_checkpoint.create_checkpoint(
            value=sample_value,
            owner_address="0x1234567890abcdef",
            block_height=99  # 假设交易在区块100确认，检查点记录区块99
        )

        assert success == True

        # 验证检查点存在
        checkpoint = temp_checkpoint.get_checkpoint(sample_value)
        assert checkpoint is not None
        assert checkpoint.owner_address == "0x1234567890abcdef"
        assert checkpoint.block_height == 99

    def test_update_checkpoint(self, temp_checkpoint, sample_value):
        """测试更新检查点"""
        # 创建原始检查点
        temp_checkpoint.create_checkpoint(
            value=sample_value,
            owner_address="0x1234567890abcdef",
            block_height=99
        )

        # 更新检查点
        success = temp_checkpoint.update_checkpoint(
            value=sample_value,
            new_owner_address="0xfedcba0987654321",
            new_block_height=199
        )

        assert success == True

        # 验证更新
        checkpoint = temp_checkpoint.get_checkpoint(sample_value)
        assert checkpoint.owner_address == "0xfedcba0987654321"
        assert checkpoint.block_height == 199

    def test_trigger_checkpoint_verification(self, temp_checkpoint, sample_value):
        """测试触发检查点验证"""
        # 创建检查点
        temp_checkpoint.create_checkpoint(
            value=sample_value,
            owner_address="0x1234567890abcdef",
            block_height=99
        )

        # 正确的验证触发
        result = temp_checkpoint.trigger_checkpoint_verification(
            value=sample_value,
            expected_owner="0x1234567890abcdef"
        )
        assert result is not None
        assert result.owner_address == "0x1234567890abcdef"

        # 错误的验证触发
        result = temp_checkpoint.trigger_checkpoint_verification(
            value=sample_value,
            expected_owner="0xwrongaddress"
        )
        assert result is None

    def test_find_checkpoints_by_owner(self, temp_checkpoint):
        """测试按所有者查找检查点"""
        # 创建多个Value
        value1 = Value("0x1000", 50)
        value2 = Value("0x2000", 75)
        value3 = Value("0x3000", 25)

        # 为同一个所有者创建多个检查点
        temp_checkpoint.create_checkpoint(value1, "0xowner123", 50)
        temp_checkpoint.create_checkpoint(value2, "0xowner123", 75)
        temp_checkpoint.create_checkpoint(value3, "0xowner456", 25)

        # 查找owner123的检查点
        owner123_checkpoints = temp_checkpoint.find_checkpoints_by_owner("0xowner123")
        assert len(owner123_checkpoints) == 2

        # 查找owner456的检查点
        owner456_checkpoints = temp_checkpoint.find_checkpoints_by_owner("0xowner456")
        assert len(owner456_checkpoints) == 1

    def test_delete_checkpoint(self, temp_checkpoint, sample_value):
        """测试删除检查点"""
        # 创建检查点
        temp_checkpoint.create_checkpoint(
            sample_value,
            "0x1234567890abcdef",
            99
        )

        # 验证存在
        checkpoint = temp_checkpoint.get_checkpoint(sample_value)
        assert checkpoint is not None

        # 删除检查点
        success = temp_checkpoint.delete_checkpoint(sample_value)
        assert success == True

        # 验证已删除
        checkpoint = temp_checkpoint.get_checkpoint(sample_value)
        assert checkpoint is None

    def test_serialization(self, temp_checkpoint, sample_value):
        """测试序列化和反序列化"""
        # 创建检查点
        temp_checkpoint.create_checkpoint(
            sample_value,
            "0x1234567890abcdef",
            99
        )

        checkpoint = temp_checkpoint.get_checkpoint(sample_value)

        # 序列化
        json_str = temp_checkpoint.serialize_to_json(checkpoint)
        assert json_str is not None
        assert "value_begin_index" in json_str
        assert "value_num" in json_str

        # 反序列化
        restored_checkpoint = temp_checkpoint.deserialize_from_json(json_str)
        assert restored_checkpoint.value_begin_index == checkpoint.value_begin_index
        assert restored_checkpoint.value_num == checkpoint.value_num
        assert restored_checkpoint.owner_address == checkpoint.owner_address
        assert restored_checkpoint.block_height == checkpoint.block_height

    def test_export_import_checkpoints(self, temp_checkpoint):
        """测试导出和导入检查点"""
        # 创建多个检查点
        value1 = Value("0x1000", 50)
        value2 = Value("0x2000", 75)

        temp_checkpoint.create_checkpoint(value1, "0xowner123", 50)
        temp_checkpoint.create_checkpoint(value2, "0xowner456", 75)

        # 导出检查点
        export_file = tempfile.mktemp(suffix='.json')
        success = temp_checkpoint.export_checkpoints(export_file)
        assert success == True
        assert os.path.exists(export_file)

        # 创建新的CheckPoint实例并导入
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            new_db_path = tmp.name

        try:
            new_checkpoint = CheckPoint(new_db_path)
            imported_count = new_checkpoint.import_checkpoints(export_file)
            assert imported_count == 2

            # 验证导入的检查点
            imported_value1_checkpoint = new_checkpoint.get_checkpoint(value1)
            imported_value2_checkpoint = new_checkpoint.get_checkpoint(value2)

            assert imported_value1_checkpoint is not None
            assert imported_value1_checkpoint.owner_address == "0xowner123"
            assert imported_value2_checkpoint is not None
            assert imported_value2_checkpoint.owner_address == "0xowner456"

        finally:
            # 清理 - Windows需要先关闭连接
            new_checkpoint = None
            import time
            time.sleep(0.1)
            try:
                if os.path.exists(new_db_path):
                    os.unlink(new_db_path)
            except PermissionError:
                pass
            try:
                if os.path.exists(export_file):
                    os.unlink(export_file)
            except PermissionError:
                pass

    def test_cache_functionality(self, temp_checkpoint, sample_value):
        """测试缓存功能"""
        # 创建检查点
        temp_checkpoint.create_checkpoint(
            sample_value,
            "0x1234567890abcdef",
            99
        )

        # 检查缓存统计
        stats = temp_checkpoint.get_cache_stats()
        assert stats['cache_size'] == 1
        assert len(stats['cached_value_keys']) == 1

        # 清空缓存
        temp_checkpoint.clear_cache()
        stats = temp_checkpoint.get_cache_stats()
        assert stats['cache_size'] == 0
        assert len(stats['cached_value_keys']) == 0

    def test_error_handling(self, temp_checkpoint):
        """测试错误处理"""
        value = Value("0x1000", 50)

        # 测试无效的owner_address
        with pytest.raises(ValueError):
            temp_checkpoint.create_checkpoint(value, "", 99)

        with pytest.raises(ValueError):
            temp_checkpoint.create_checkpoint(value, None, 99)

        # 测试无效的block_height
        with pytest.raises(ValueError):
            temp_checkpoint.create_checkpoint(value, "0x123", -1)

        # 测试无效的value类型
        with pytest.raises(TypeError):
            temp_checkpoint.create_checkpoint("not_a_value", "0x123", 99)

    def test_containing_checkpoint_verification(self, temp_checkpoint):
        """测试包含检查点验证功能"""
        # 创建一个大的Value作为检查点
        large_value = Value("0x1000", 100)
        temp_checkpoint.create_checkpoint(large_value, "0xAlice", 99)

        # 模拟Value被拆分后的场景
        # 假设large_value被拆分成多个子Value
        split_value1 = Value("0x1000", 30)  # 前部30个值
        split_value2 = Value("0x1020", 40)  # 中部40个值
        split_value3 = Value("0x1050", 20)  # 后部20个值

        # 测试拆分后的Value能触发检查点验证
        result1 = temp_checkpoint.trigger_checkpoint_verification(split_value1, "0xAlice")
        assert result1 is not None
        assert result1.owner_address == "0xAlice"
        assert result1.contains_value(split_value1) == True

        result2 = temp_checkpoint.trigger_checkpoint_verification(split_value2, "0xAlice")
        assert result2 is not None
        assert result2.owner_address == "0xAlice"
        assert result2.contains_value(split_value2) == True

        result3 = temp_checkpoint.trigger_checkpoint_verification(split_value3, "0xAlice")
        assert result3 is not None
        assert result3.owner_address == "0xAlice"
        assert result3.contains_value(split_value3) == True

        # 测试错误的所有者不会触发验证
        wrong_owner_result = temp_checkpoint.trigger_checkpoint_verification(split_value1, "0xWrongOwner")
        assert wrong_owner_result is None

        # 测试超出范围的Value不会触发验证
        outside_value = Value("0x2000", 50)
        outside_result = temp_checkpoint.trigger_checkpoint_verification(outside_value, "0xAlice")
        assert outside_result is None

    def test_find_containing_checkpoint(self, temp_checkpoint):
        """测试查找包含检查点功能"""
        # 创建多个检查点
        value1 = Value("0x1000", 100)  # 0x1000-0x1063
        value2 = Value("0x2000", 50)   # 0x2000-0x2031
        value3 = Value("0x3000", 75)   # 0x3000-0x304A

        temp_checkpoint.create_checkpoint(value1, "0xAlice", 100)
        temp_checkpoint.create_checkpoint(value2, "0xBob", 200)
        temp_checkpoint.create_checkpoint(value3, "0xCharlie", 300)

        # 测试精确匹配
        exact_match = temp_checkpoint.find_containing_checkpoint(value1)
        assert exact_match is not None
        assert exact_match.owner_address == "0xAlice"

        # 测试包含匹配
        sub_value = Value("0x1020", 30)  # 在value1范围内
        containing_match = temp_checkpoint.find_containing_checkpoint(sub_value)
        assert containing_match is not None
        assert containing_match.owner_address == "0xAlice"
        assert containing_match.contains_value(sub_value) == True

        # 测试没有匹配的情况
        no_match_value = Value("0x4000", 50)
        no_match = temp_checkpoint.find_containing_checkpoint(no_match_value)
        assert no_match is None

if __name__ == "__main__":
    pytest.main([__file__, "-v"])