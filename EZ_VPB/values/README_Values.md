# EZ_Value 代码结构说明

## 概述

EZ_Value 模块是 EZChain 区块链系统中用于管理 Value（数值）的核心组件，提供了完整的值管理、状态跟踪和交易选择功能。

## 核心类

### 1. Value 类 (`Value.py`)

**功能**: 基础 Value 数据结构，表示区块链上的数值单位

**主要特性**:
- 使用 16 进制 `beginIndex` 和 10 进制 `valueNum` 定义值的范围
- 支持状态管理：未花销、已选中、本地提交、已确认
- 提供值分割、交集检测等核心操作

**关键方法**:
- `split_value()`: 分割值，用于找零操作
- `is_intersect_value()`: 检测值重叠
- `get_intersect_value()`: 获取交集部分
- `check_value()`: 验证值的有效性

### 2. ValueNode 类 (`AccountValueCollection.py`)

**功能**: 链表节点，用于在 AccountValueCollection 中组织 Value

**结构**:
- 包含 Value 对象
- 维护前后指针（双向链表）
- 使用 UUID 作为唯一标识符

### 3. AccountValueCollection 类 (`AccountValueCollection.py`)

**功能**: 账户 Value 集合管理，使用链表结构避免索引混乱

**核心功能**:
- **链表管理**: 添加、删除、遍历 Value
- **状态索引**: 按状态快速查找 Value
- **范围查询**: 支持按十进制范围查找
- **值操作**: 分裂、合并（暂时禁用）Value
- **余额计算**: 按状态计算账户余额

**关键方法**:
- `add_value()`: 添加 Value 到集合
- `split_value()`: 分裂指定 Value
- `find_by_state()`: 按状态查找
- `get_balance_by_state()`: 计算状态余额
- `validate_integrity()`: 验证集合完整性

### 4. AccountPickValues 类 (`AccountPickValues.py`)

**功能**: 增强版 Value 选择器，集成 AccountValueCollection 实现高效交易调度

**核心功能**:
- **交易准备**: 选择合适的 Value 组合满足交易金额
- **找零处理**: 自动处理找零值分裂和状态更新
- **状态管理**: 交易过程中的 Value 状态流转
- **余额查询**: 提供账户余额和 Value 列表

**主要流程**:
1. `pick_values_for_transaction()`: 贪心算法选择 Value
2. 创建找零交易和主交易
3. 更新 Value 状态为 SELECTED
4. 支持提交、确认、回滚操作

## Value 状态流转

```
UNSPENT → SELECTED → LOCAL_COMMITTED → CONFIRMED
    ↑                                        ↓
    ←────────────── 回滚 ←───────────────────
```

- **UNSPENT**: 未花销状态，可用于交易
- **SELECTED**: 已选中，准备注入交易
- **LOCAL_COMMITTED**: 本地提交待确认
- **CONFIRMED**: 链上已确认（=已花费）

## 架构优势

1. **索引清晰**: 使用链表结构避免传统索引混乱问题
2. **高效查询**: 多级索引支持快速状态和范围查询
3. **状态安全**: 完整的状态流转机制，支持交易回滚
4. **内存优化**: 链表结构避免大量内存拷贝
5. **完整性保证**: 多重验证确保数据一致性

## 使用示例

```python
# 创建 Value 集合
collection = AccountValueCollection(account_address)

# 添加 Value
value = Value("0x1000", 1000)
collection.add_value(value)

# 选择 Value 进行交易
picker = AccountPickValues(account_address, collection)
selected, change, change_tx, main_tx = picker.pick_values_for_transaction(
    required_amount=500,
    sender="address1",
    recipient="address2",
    nonce=1,
    time="2024-01-01"
)
```

EZ_Value 模块为 EZChain 系统提供了稳定、高效的 Value 管理能力，是整个交易系统的核心基础组件。