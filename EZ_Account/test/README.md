# EZ_Account测试模块

这是EZChain账户系统的完整测试套件，提供了多层次的测试功能来验证系统的正确性、稳定性和性能。

## 📁 目录结构

```
test/
├── __init__.py                 # 模块初始化
├── README.md                  # 本文档
├── config.py                  # 测试配置
├── core/                      # 核心功能测试
│   ├── __init__.py
│   └── account_test.py        # Account类核心测试
├── functional/                # 功能性测试
│   ├── __init__.py
│   ├── integration_test.py    # 集成测试
│   └── multi_account_test.py  # 多账户测试
├── utils/                     # 测试工具
│   ├── __init__.py
│   ├── debug_tools.py         # 调试工具
│   ├── test_runner.py         # 测试运行器
│   └── report_generator.py    # 报告生成器
└── docs/                      # 文档
    ├── __init__.py
    └── README_MultiAccountTest.md  # 多账户测试说明
```

## 🚀 快速开始

### 运行所有测试
```bash
cd EZ_Account/test
python -m utils.test_runner all
```

### 运行特定测试
```bash
# 核心功能测试
python -m utils.test_runner account

# 集成测试
python -m utils.test_runner integration

# 多账户测试
python -m utils.test_runner multi-account

# 调试测试
python -m utils.test_runner debug
```

### 使用预设配置
```bash
# 快速测试
python -m utils.test_runner --quick

# 压力测试
python -m utils.test_runner --stress
```

## 📊 测试类型

### 1. 核心功能测试 (AccountTest)
测试Account类的基本功能：
- 账户创建和初始化
- 余额查询（修复版本）
- VPB管理
- 交易创建
- 数字签名验证

**使用方法**：
```python
from test.core.account_test import AccountTest

test = AccountTest()
result = test.run_basic_test_suite()
```

### 2. 集成测试 (IntegrationTest)
测试Account与其他EZChain模块的集成：
- VPBManager集成
- CreateMultiTransactions集成
- 跨模块数据一致性

**使用方法**：
```python
from test.functional.integration_test import IntegrationTest

test = IntegrationTest()
result = test.run_integration_test(num_accounts=3, num_transactions=5)
```

### 3. 多账户测试 (MultiAccountTest)
模拟多账户环境：
- 多账户并发交易
- 模拟交易池和区块链
- 线程安全的并发操作

**使用方法**：
```python
from test.functional.multi_account_test import MultiAccountTest

test = MultiAccountTest()
result = test.run_multi_account_test(num_accounts=3, num_transactions=5)
```

### 4. 调试工具 (DebugTools)
提供强大的调试功能：
- 账户余额问题诊断
- VPB完整性验证
- 状态一致性检查

**使用方法**：
```python
from test.utils.debug_tools import DebugTools

tools = DebugTools()
tools.run_full_debug("debug_account", 1000)
```

## ⚙️ 配置选项

### 预定义配置
- **QUICK_TEST_CONFIG**: 快速测试（2个账户，10秒）
- **STANDARD_TEST_CONFIG**: 标准测试（3个账户，30秒）
- **STRESS_TEST_CONFIG**: 压力测试（5个账户，2分钟）

### 自定义配置
```python
from test.config import IntegrationTestConfig

config = IntegrationTestConfig(
    num_accounts=5,
    base_balance=2000,
    test_transactions=10,
    transaction_amount_range=(50, 500),
    test_duration=60
)
```

## 🐛 已知问题

### VPBManager余额查询问题
在VPBManager中发现了一个余额查询问题：
- **问题**: `get_unspent_values()`返回空列表，但底层数据正确
- **影响**: 不影响核心功能，仅影响查询接口
- **解决方案**: 使用修复版本的余额查询方法

**修复方法**：
```python
def get_available_balance(account):
    return account.vpb_manager.value_collection.get_balance_by_state(ValueState.UNSPENT)
```

## 📈 性能指标

### 典型测试结果
- **账户创建**: < 1秒/账户
- **交易创建**: < 0.1秒/交易
- **多账户TPS**: 1-5 TPS
- **内存使用**: < 50MB（3个账户测试）

### 性能优化建议
1. 使用快速测试进行日常验证
2. 在CI/CD环境中使用标准测试
3. 定期运行压力测试
4. 监控测试执行时间

## 📋 测试清单

运行测试前确认：
- [ ] 项目依赖已安装
- [ ] 有足够的磁盘空间（>100MB）
- [ ] 系统支持多线程

测试完成后检查：
- [ ] 所有测试通过
- [ ] 无严重错误
- [ ] 性能指标正常
- [ ] 测试报告生成

## 🔧 故障排除

### 常见问题

#### 1. 导入错误
```bash
# 确保在项目根目录运行
cd d:/real_EZchain
python -m EZ_Account.test.utils.test_runner
```

#### 2. 权限错误
```bash
# 确保有临时目录写入权限
python -m EZ_Account.test.utils.test_runner --temp-dir /tmp/ezchain_test
```

#### 3. 内存不足
```bash
# 减少测试规模
python -m EZ_Account.test.utils.test_runner --quick
```

### 调试模式
```bash
# 启用详细日志
python -m EZ_Account.test.utils.test_runner debug --no-cleanup
```

## 📚 相关文档

- [多账户测试详细说明](docs/README_MultiAccountTest.md)
- [EZChain项目架构文档](../../README.md)
- [Account API文档](../Account.py)

## 🤝 贡献指南

### 添加新测试
1. 在相应目录下创建测试文件
2. 遵循现有的代码风格
3. 添加适当的测试配置
4. 更新文档

### 报告问题
如发现测试问题，请提供：
- 错误信息和堆栈跟踪
- 测试配置
- 系统环境信息
- 复现步骤

---

**版本**: 1.0
**作者**: Claude & Ld Xue
**最后更新**: 2025/11/25