# EZchain Blockchain Implementation

## 概述

这是 EZchain 项目的核心区块链实现，专为主真实网络部署而设计。该实现提供了完整的分叉处理、共识机制和高效的区块链管理功能。

## 特性

### 🔧 核心功能
- **真实网络部署**: 专为分布式网络环境设计
- **完整分叉处理**: 自动分叉检测、解决和共识管理
- **高效共识机制**: 基于区块数量的自动确认机制
- **性能优化**: 智能缓存和快速查找系统
- **模块化设计**: 与 EZchain 生态系统无缝集成

### 🏗️ 架构特点
- **现代化 Python**: 使用类型提示、数据类和枚举
- **可配置性**: 灵活的配置系统支持不同网络环境
- **错误处理**: 完善的异常处理和日志记录
- **可扩展性**: 易于扩展的架构设计

## 快速开始

### 基本用法

```python
from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig

# 创建区块链（真实网络模式）
config = ChainConfig(debug_mode=True)
blockchain = Blockchain(config=config)

# 添加区块
block = Block(
    index=1,
    m_tree_root="merkle_root",
    miner="miner_name",
    pre_hash=blockchain.get_latest_block_hash()
)
main_chain_updated = blockchain.add_block(block)

# 获取最新区块
latest = blockchain.get_latest_block()
print(f"Latest block: #{latest.get_index()}")
print(f"Main chain updated: {main_chain_updated}")
```

### 分叉处理

```python
# 创建区块链
blockchain = Blockchain(config=ChainConfig())

# 添加区块到主链
blockchain.add_block(block1)
blockchain.add_block(block2)

# 创建分叉（指向较早的区块）
fork_block = Block(
    index=3,
    m_tree_root="fork_root",
    miner="fork_miner",
    pre_hash=block1.get_hash()  # 从 block1 分叉
)
blockchain.add_block(fork_block)

# 如果分叉链更长，会自动更新主链
stats = blockchain.get_fork_statistics()
print(f"Fork nodes: {stats['fork_nodes']}")
```

## 架构设计

### 核心类

#### 1. `Blockchain`
主区块链类，负责管理整个区块链状态。

**主要方法**:
- `add_block(block)`: 添加区块到区块链（自动处理分叉）
- `get_block_by_index(index)`: 按索引获取区块
- `get_block_by_hash(hash)`: 按哈希获取区块（搜索主链和分叉树）
- `is_valid_chain()`: 验证区块链完整性
- `get_latest_confirmed_block_index()`: 获取最新确认区块

#### 2. `ForkNode`
分叉树节点类，用于管理分叉结构。

**主要方法**:
- `add_child(child)`: 添加子节点
- `find_by_hash(hash)`: 按哈希查找节点
- `get_chain_path()`: 获取链路径
- `get_longest_path()`: 获取最长路径

#### 3. `ChainConfig`
区块链配置类，用于设置区块链参数。

**配置选项**:
- `max_fork_height`: 最大分叉高度
- `confirmation_blocks`: 确认所需区块数
- `enable_fork_resolution`: 是否启用分叉解决
- `debug_mode`: 调试模式

#### 4. `ConsensusStatus`
枚举类，定义共识状态：
- `PENDING`: 待确认
- `CONFIRMED`: 已确认
- `ORPHANED`: 孤块

## 分叉处理机制

### 分叉检测
当新区块不直接延长主链时，系统自动创建分叉：

```python
# 主链: Genesis -> Block A -> Block B
# 新区块 C 指向 Block A，创建分叉
# 结果: Genesis -> Block A -> [Block B, Block C (fork)]
```

### 分叉解决
系统自动选择最长链作为主链：

1. **长度优先**: 更长的链成为主链
2. **高度相同**: 保持当前主链
3. **状态更新**: 自动更新共识状态

### 共识机制
- **确认规则**: `latest_index - confirmation_blocks + 1`
- **状态管理**: PENDING → CONFIRMED → ORPHANED
- **自动更新**: 每次添加区块后更新状态

## API 参考

### 基本操作

```python
# 基本操作
len(blockchain)                    # 获取链长度
blockchain.get_chain_length()       # 获取链长度
blockchain.get_latest_block()       # 获取最新区块
blockchain.get_latest_block_hash()  # 获取最新区块哈希
blockchain.get_latest_block_index() # 获取最新区块索引

# 区块查询
blockchain.get_block_by_index(5)    # 按索引查询
blockchain.get_block_by_hash(hash)  # 按哈希查询
blockchain.is_block_in_main_chain(hash)  # 检查是否在主链

# 验证操作
blockchain.is_valid_chain()         # 验证链完整性
blockchain.is_block_confirmed(hash) # 检查区块确认状态
```

### 分叉操作

```python
# 分叉操作
fork_node = blockchain.get_fork_node_by_hash(hash)
fork_node = blockchain.get_fork_node_by_index(index)
forks = blockchain.get_all_forks_at_height(height)

# 统计信息
stats = blockchain.get_fork_statistics()
print(f"Total nodes: {stats['total_nodes']}")
print(f"Fork nodes: {stats['fork_nodes']}")
print(f"Confirmed nodes: {stats['confirmed_nodes']}")

# 可视化
blockchain.print_fork_tree()       # 打印分叉树
blockchain.print_chain_info()      # 打印链信息
```

## 配置选项

### 基本配置

```python
config = ChainConfig(
    max_fork_height=6,               # 最大分叉高度
    confirmation_blocks=6,           # 确认区块数
    enable_fork_resolution=True,     # 启用分叉解决
    debug_mode=False                 # 调试模式
)
blockchain = Blockchain(config=config)
```

### 推荐配置

#### 开发环境
```python
dev_config = ChainConfig(
    max_fork_height=4,
    confirmation_blocks=3,
    debug_mode=True
)
```

#### 生产环境
```python
prod_config = ChainConfig(
    max_fork_height=10,
    confirmation_blocks=6,
    enable_fork_resolution=True,
    debug_mode=False
)
```

#### 高吞吐量网络
```python
high_throughput_config = ChainConfig(
    max_fork_height=8,
    confirmation_blocks=4,
    enable_fork_resolution=True,
    debug_mode=False
)
```

## 分叉场景示例

### 基本分叉场景

```python
# 创建区块链
blockchain = Blockchain()

# 构建主链
genesis = blockchain.get_latest_block()
block1 = Block(index=1, miner="miner_1", pre_hash=genesis.get_hash())
block2 = Block(index=2, miner="miner_2", pre_hash=block1.get_hash())
blockchain.add_block(block1)
blockchain.add_block(block2)

# 创建分叉（从 block1 分叉）
fork_block1 = Block(index=2, miner="fork_miner_1", pre_hash=block1.get_hash())
fork_block2 = Block(index=3, miner="fork_miner_2", pre_hash=fork_block1.get_hash())
blockchain.add_block(fork_block1)
blockchain.add_block(fork_block2)

# 分叉链更长，自动成为主链
print(f"Latest block: {blockchain.get_latest_block().get_miner()}")
# 输出: fork_miner_2
```

### 复杂分叉场景

```python
# 多重分叉
block_a = Block(index=1, miner="miner_A", pre_hash=genesis.get_hash())
block_b = Block(index=2, miner="miner_B", pre_hash=block_a.get_hash())
block_c = Block(index=3, miner="miner_C", pre_hash=block_b.get_hash())

# 从 block_A 创建不同分叉
fork_d = Block(index=2, miner="miner_D", pre_hash=block_a.get_hash())
fork_e = Block(index=3, miner="miner_E", pre_hash=fork_d.get_hash())
fork_f = Block(index=4, miner="miner_F", pre_hash=fork_e.get_hash())

# 从 block_B 创建另一个分叉
fork_g = Block(index=3, miner="miner_G", pre_hash=block_b.get_hash())

# 系统会自动选择最长链
```

## 错误处理

### 常见异常

```python
try:
    blockchain.add_block(invalid_block)
except ValueError as e:
    print(f"Block validation failed: {e}")

# Genesis 块错误
if genesis_block.get_index() != 0:
    raise ValueError("Genesis block must have index 0")

# 父区块不存在
if parent_block is None:
    raise ValueError("Parent block not found")
```

### 日志记录

```python
import logging

# 启用调试日志
config = ChainConfig(debug_mode=True)
blockchain = Blockchain(config=config)

# 日志级别
# DEBUG: 详细的调试信息
# INFO:  一般信息（区块添加、分叉解决等）
# ERROR: 错误信息（验证失败、配置错误等）
```

## 集成示例

### 与 MerkleTree 集成

```python
from EZ_Units.MerkleTree import MerkleTree

# 创建交易数据
transactions = ["tx1", "tx2", "tx3"]
merkle_tree = MerkleTree(transactions)

# 创建区块
block = Block(
    index=1,
    m_tree_root=merkle_tree.get_root_hash(),
    miner="miner",
    pre_hash=blockchain.get_latest_block_hash()
)
blockchain.add_block(block)
```

### 与 Bloom Filter 集成

```python
# 添加数据到 Bloom Filter
block.add_item_to_bloom("account_address")
block.add_item_to_bloom("transaction_hash")

# 查询 Bloom Filter
if block.is_in_bloom("account_address"):
    print("Account found in block")
```

## 性能优化

### 缓存机制
- **哈希缓存**: O(1) 哈希查找
- **索引缓存**: O(1) 索引查找
- **路径缓存**: 优化的链路径计算

### 内存管理
- **按需加载**: 不一次性加载所有区块
- **智能清理**: 自动清理孤立数据
- **批处理**: 支持批量操作

## 测试

### 运行测试

```bash
# 运行所有测试
python -m pytest EZ_Test/test_blockchain.py -v

# 运行特定测试
python -m pytest EZ_Test/test_blockchain.py::TestBlockchainForkHandling -v

# 运行演示
python EZ_Test/demo_blockchain.py
```

### 测试覆盖

- **配置测试**: 验证各种配置选项
- **基本功能测试**: 验证区块链基本操作
- **分叉处理测试**: 验证分叉检测和解决
- **边界情况测试**: 验证错误处理和异常情况
- **集成测试**: 验证与其他组件的集成
- **性能测试**: 验证大规模链的性能

## 最佳实践

### 1. 网络配置
- **测试网络**: 较小的确认区块数
- **生产网络**: 标准确认区块数（6个）
- **高性能网络**: 较少的确认区块数

### 2. 分叉处理
- **监控分叉**: 定期检查分叉统计
- **及时处理**: 快速响应长链攻击
- **日志记录**: 记录所有分叉事件

### 3. 性能优化
- **批量操作**: 尽可能批量处理区块
- **缓存利用**: 充分利用内置缓存机制
- **内存管理**: 定期监控内存使用

### 4. 安全考虑
- **验证输入**: 始终验证区块数据
- **异常处理**: 妥善处理各种异常
- **日志记录**: 记录重要操作和错误

## 监控和诊断

### 分叉监控

```python
# 获取分叉统计
stats = blockchain.get_fork_statistics()
print(f"Total nodes: {stats['total_nodes']}")
print(f"Fork rate: {stats['fork_nodes'] / stats['total_nodes'] * 100:.2f}%")
print(f"Confirmed rate: {stats['confirmed_nodes'] / stats['total_nodes'] * 100:.2f}%")
```

### 链健康检查

```python
def health_check(blockchain):
    """区块链健康检查"""
    issues = []

    # 验证链完整性
    if not blockchain.is_valid_chain():
        issues.append("Chain integrity check failed")

    # 检查分叉情况
    stats = blockchain.get_fork_statistics()
    if stats['fork_nodes'] > stats['main_chain_nodes'] * 0.1:
        issues.append("High fork rate detected")

    # 检查确认延迟
    latest = blockchain.get_latest_block_index()
    confirmed = blockchain.get_latest_confirmed_block_index()
    if confirmed is not None:
        confirmation_delay = latest - confirmed
        if confirmation_delay > blockchain.config.confirmation_blocks * 2:
            issues.append(f"High confirmation delay: {confirmation_delay}")

    return issues
```

## 故障排除

### 常见问题

1. **分叉过多**
   - 检查网络同步状态
   - 验证区块验证逻辑
   - 调整确认区块数

2. **性能问题**
   - 启用调试模式检查日志
   - 监控内存使用
   - 考虑增加缓存

3. **共识问题**
   - 检查时钟同步
   - 验证网络连通性
   - 调整共识参数

## 版本历史

### v2.0.0
- 专为真实网络部署设计
- 移除模拟模式
- 优化分叉处理机制
- 改进性能和稳定性
- 增强错误处理

### v1.0.0
- 初始实现
- 支持双模式（Simulation/DST）
- 完整的分叉处理机制
- 高性能缓存系统

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个实现。

## 许可证

本项目遵循 MIT 许可证。