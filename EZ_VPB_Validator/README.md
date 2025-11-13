# EZ_VPB_Validator

EZChain VPB (Value-Proofs-BlockIndex) 验证系统的模块化重构版本。

## 项目结构

```
EZ_VPB_Validator/
├── core/                           # 核心类型和基础类
│   ├── __init__.py
│   ├── types.py                    # 核心数据类型定义
│   └── validator_base.py           # 验证器基类和通用功能
├── steps/                          # 验证步骤模块
│   ├── __init__.py
│   ├── data_structure_validator.py # 第一步：数据结构验证
│   ├── slice_generator.py          # 第二步：VPB切片生成
│   ├── bloom_filter_validator.py   # 第三步：布隆过滤器验证
│   └── proof_validator.py          # 第四步：证明验证和双花检测
├── utils/                          # 工具模块
│   ├── __init__.py
│   ├── value_intersection.py       # Value交集检测工具
│   └── epoch_extractor.py          # Epoch信息提取工具
├── __init__.py                     # 包初始化文件
├── vpb_validator.py                # 主验证器入口
└── README.md                       # 本文件
```

## 核心特性

- **模块化设计**：将复杂的验证流程分解为独立的、可测试的模块
- **清晰职责分离**：每个模块专注于特定的验证步骤
- **易于扩展**：新的验证逻辑可以作为独立的步骤添加
- **完整的错误处理**：详细的错误信息和异常处理
- **线程安全**：支持并发验证操作
- **统计功能**：验证成功率和检查点命中率统计

## 使用示例

```python
from EZ_VPB_Validator import VPBValidator, MainChainInfo

# 创建验证器
validator = VPBValidator(checkpoint=checkpoint_manager)

# 准备验证数据
main_chain_info = MainChainInfo(
    merkle_roots={...},
    bloom_filters={...},
    current_block_height=1000
)

# 执行验证
report = validator.verify_vpb_pair(
    value=value_obj,
    proofs=proofs_obj,
    block_index_list=block_index_obj,
    main_chain_info=main_chain_info,
    account_address="0x..."
)

# 检查结果
if report.is_valid:
    print("VPB验证成功")
else:
    print(f"VPB验证失败，错误数量: {len(report.errors)}")
    for error in report.errors:
        print(f"  - {error.error_type}: {error.error_message}")

# 获取统计信息
stats = validator.get_verification_stats()
print(f"验证成功率: {stats['success_rate']:.2%}")
```

## 验证流程

### 第一步：数据结构验证
- 验证Value、Proofs、BlockIndexList的基础类型和格式
- 检查VPB特定的数据一致性
- 使用现有类的验证方法

### 第二步：VPB切片生成
- 检查点匹配和优化
- 生成验证所需的历史切片
- 处理创世块的特殊情况

### 第三步：布隆过滤器验证
- 验证VPB数据与主链的一致性
- 检测隐藏的恶意区块
- 验证区块连续性和完整性

### 第四步：证明验证和双花检测
- 验证每个proof unit的Merkle证明
- 检测双花攻击
- 验证价值转移的有效性

## 与原版本对比

### 优点
1. **模块化**：每个验证步骤都是独立的模块，便于单独测试和维护
2. **可扩展**：新的验证逻辑可以轻松添加为新步骤
3. **清晰的职责**：每个模块专注于特定功能
4. **更好的错误处理**：统一的错误类型和报告格式
5. **详细的日志**：每个步骤都有详细的日志记录

### 兼容性
- 保持与原VPBVerify.py相同的验证逻辑和结果
- 支持相同的输入输出接口
- 兼容现有的CheckPoint和其他EZChain组件

## 测试

每个模块都可以独立测试：

```python
# 测试数据结构验证
from EZ_VPB_Validator.steps import DataStructureValidator
validator = DataStructureValidator()
result = validator.validate_basic_data_structure(value, proofs, block_index_list)

# 测试布隆过滤器验证
from EZ_VPB_Validator.steps import BloomFilterValidator
validator = BloomFilterValidator()
result = validator.verify_bloom_filter_consistency(vpb_slice, main_chain_info)
```

## 迁移指南

从原VPBVerify.py迁移到新的模块化版本：

1. 替换导入：
   ```python
   # 原版本
   from EZ_VPB.VPBVerify import VPBVerify

   # 新版本
   from EZ_VPB_Validator import VPBValidator
   ```

2. 创建验证器实例：
   ```python
   # 原版本
   verifier = VPBVerify(checkpoint=checkpoint, logger=logger)

   # 新版本
   verifier = VPBValidator(checkpoint=checkpoint, logger=logger)
   ```

3. 验证接口保持不变，可以直接替换使用。

## 开发和贡献

- 添加新的验证步骤时，请继承`ValidatorBase`基类
- 保持与现有模块的接口一致性
- 添加完整的单元测试
- 更新文档和示例