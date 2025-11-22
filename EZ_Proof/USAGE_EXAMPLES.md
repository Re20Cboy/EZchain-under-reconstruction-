# EZ_Proof 使用示例和迁移指南

## 概述

EZ_Proof模块经过重构，提供了更好的架构设计。新的`AccountProofManager`类提供了Account级别的统一管理接口，解决了原有设计中的局限性。

## 主要改进

### 原有问题
1. `Proofs`类以单个Value为视角，缺乏Account级别的统一管理
2. 存储结构分散，没有向Account提供唯一的管理接口
3. 映射关系管理复杂，难以维护

### 新架构优势
1. **Account级别管理**: `AccountProofManager`提供统一的Account视角管理接口
2. **优化的存储**: `AccountProofStorage`提供更高效的持久化存储
3. **避免重复**: 自动管理ProofUnit的唯一性和引用计数
4. **向后兼容**: 保持与现有代码的兼容性

## 新架构使用示例

### 1. 创建AccountProofManager

```python
from EZ_Proof import AccountProofManager, create_account_proof_manager

# 方法1: 直接创建
manager = AccountProofManager("0x1234567890abcdef")

# 方法2: 使用工厂函数（推荐）
manager = create_account_proof_manager("0x1234567890abcdef", "custom_db.db")
```

### 2. 添加Value和ProofUnit

```python
from EZ_Value.Value import Value, ValueState
from EZ_Proof.ProofUnit import ProofUnit

# 创建Value
value = Value("0x1000", 100, ValueState.UNSPENT)

# 添加Value到管理器
manager.add_value(value)

# 创建ProofUnit（需要MultiTransactions和MerkleTreeProof）
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Units.MerkleProof import MerkleTreeProof

# 假设已经有了这些对象
multi_txns = MultiTransactions(...)
mt_proof = MerkleTreeProof(...)

# 创建ProofUnit
proof_unit = ProofUnit(
    owner="0x1234567890abcdef",
    owner_multi_txns=multi_txns,
    owner_mt_proof=mt_proof
)

# 添加ProofUnit到指定Value
manager.add_proof_unit(value.begin_index, proof_unit)
```

### 3. 查询和管理

```python
# 获取账户所有Value
all_values = manager.get_all_values()

# 获取指定Value的所有ProofUnit
proof_units = manager.get_proof_units_for_value("0x1000")

# 根据owner获取ProofUnit
owner_proofs = manager.get_proof_units_by_owner("0x1234567890abcdef")

# 获取所有Value-ProofUnit关系
all_relations = manager.get_all_proof_units()

# 验证所有ProofUnit
verification_results = manager.verify_all_proof_units("merkle_root_hash")
for value_id, unit_id, is_valid, error in verification_results:
    print(f"Value {value_id}, Unit {unit_id}: {'✓' if is_valid else f'✗ ({error})'}")
```

### 4. 统计信息

```python
# 获取管理器统计信息
stats = manager.get_statistics()
print(f"总Values: {stats['total_values']}")
print(f"总ProofUnits: {stats['total_proof_units']}")
print(f"每个Value平均ProofUnits: {stats['avg_proofs_per_value']:.2f}")
```

### 5. 删除和清理

```python
# 删除Value及其所有ProofUnit映射
manager.remove_value("0x1000")

# 移除特定的Value-ProofUnit映射
manager.remove_value_proof_mapping("0x1000", "unit_id_123")

# 清除所有数据
manager.clear_all()
```

## 从旧架构迁移

### 迁移现有Proofs对象

```python
from EZ_Proof import Proofs, migrate_legacy_proofs

# 假设有一个现有的Proofs对象
legacy_proofs = Proofs("value_123")

# 迁移到新的AccountProofManager
new_manager = migrate_legacy_proofs(legacy_proofs, "0x1234567890abcdef")

# 现在可以使用新的管理器
print(f"Migrated {len(new_manager)} values")
```

### 兼容性使用

```python
# 旧的Proofs类仍然可用，但会显示弃用警告
legacy_proofs = Proofs("value_123", account_address="0x1234567890abcdef")

# 可以传入AccountProofManager来使用新架构
new_manager = AccountProofManager("0x1234567890abcdef")
compatible_proofs = Proofs("value_123", account_proof_manager=new_manager)

# 这样就可以使用旧的API，但底层使用新的存储架构
```

## 最佳实践

### 1. 初始化设置

```python
class AccountManager:
    def __init__(self, account_address: str):
        self.account_address = account_address
        self.proof_manager = AccountProofManager(account_address)
        self.value_collection = AccountValueCollection(account_address)

    def add_transaction_proof(self, value: Value, multi_txns, mt_proof):
        """添加交易证明的完整流程"""
        # 1. 添加Value到集合
        self.value_collection.add_value(value)

        # 2. 添加Value到Proof管理器
        self.proof_manager.add_value(value)

        # 3. 创建并添加ProofUnit
        proof_unit = ProofUnit(
            owner=self.account_address,
            owner_multi_txns=multi_txns,
            owner_mt_proof=mt_proof
        )

        return self.proof_manager.add_proof_unit(value.begin_index, proof_unit)
```

### 2. 批量操作

```python
def batch_add_proofs(manager: AccountProofManager, value_proof_pairs: List[Tuple[Value, ProofUnit]]):
    """批量添加Value和ProofUnit"""
    for value, proof_unit in value_proof_pairs:
        manager.add_value(value)
        manager.add_proof_unit(value.begin_index, proof_unit)

    print(f"批量添加完成: {len(value_proof_pairs)} 个Values")
```

### 3. 验证和清理

```python
def verify_and_cleanup(manager: AccountProofManager):
    """验证所有ProofUnit并清理无效数据"""
    # 验证所有ProofUnit
    results = manager.verify_all_proof_units()

    invalid_count = 0
    for value_id, unit_id, is_valid, error in results:
        if not is_valid:
            print(f"无效ProofUnit: {unit_id} ({error})")
            manager.remove_value_proof_mapping(value_id, unit_id)
            invalid_count += 1

    print(f"验证完成，清理了 {invalid_count} 个无效ProofUnit")
    return invalid_count == 0
```

## 性能优化建议

### 1. 内存管理
- `AccountProofManager`会自动管理内存缓存
- 对于大量数据，考虑定期调用清理操作
- 使用批量操作减少数据库访问次数

### 2. 数据库优化
- 为常用查询字段创建索引
- 定期清理已删除的ProofUnit
- 考虑使用连接池优化数据库性能

### 3. 并发处理
```python
import threading

class ThreadSafeAccountProofManager:
    def __init__(self, account_address: str):
        self.manager = AccountProofManager(account_address)
        self.lock = threading.RLock()

    def add_proof_unit_safe(self, value_id: str, proof_unit: ProofUnit):
        with self.lock:
            return self.manager.add_proof_unit(value_id, proof_unit)
```

## 常见问题

### Q: 如何处理ProofUnit重复添加？
A: `AccountProofManager`会自动检测重复的ProofUnit，增加引用计数而不是创建重复数据。

### Q: 如何迁移现有数据？
A: 使用`migrate_legacy_proofs()`函数，或者手动遍历现有数据重新添加到新的管理器中。

### Q: 新架构与旧架构的性能比较？
A: 新架构有以下优势：
- 减少ProofUnit重复存储
- 优化了Account级别的查询
- 更好的索引和缓存机制
- 支持批量操作

### Q: 是否需要立即迁移？
A: 不需要。旧的`Proofs`类仍然可用，但建议新项目使用新架构，现有项目可以逐步迁移。