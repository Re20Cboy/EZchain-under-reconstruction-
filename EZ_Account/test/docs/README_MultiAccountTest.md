# EZChain多账户集成测试系统

这是一个完整的多进程多账户节点功能模拟测试系统，用于验证EZChain区块链项目中各模块的集成正确性。

## 🎯 测试目标

根据`MultiAccountTest`纲要，本测试系统实现：

1. **四进程架构**：主链共识节点 + 3个账户节点（A、B、C）
2. **完整交易流程**：交易生成 → 签名 → 提交 → 打包 → 确认 → VPB更新
3. **模块联调验证**：验证主链、账户节点、交易池、VPB管理等核心模块
4. **稳定性测试**：模拟持续交易环境，观察系统稳定性

目前integration_test.py缺少以下内容：
1）创建一个主链共识节点，用于维护主链信息和交易池
2）Account生成的交易提交至交易池
3）主链共识节点打包交易池生成区块，并将相关数据（用于更新account的VPB的数据：区块高度、默克尔树证明等，具体参考VPBManager.py中的操作方法所需要的输入）反传给对应的Sender节点。
4）Account节点利用VPBManager更新本地的VPB数据。

## 📁 文件结构

```
EZ_Account/
├── multi_account_integration_test.py  # 核心测试实现
├── run_multi_account_test.py         # 测试运行器
├── test_analyzer.py                  # 测试结果分析器
├── README_MultiAccountTest.md        # 本文档
└── MultiAccountTest                  # 测试纲要
```

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+
- 已安装项目依赖
- 支持多进程的系统环境

### 2. 运行测试

#### 快速测试（推荐初试）
```bash
python run_multi_account_test.py --quick
```

#### 标准测试
```bash
python run_multi_account_test.py --custom --accounts 3 --duration 30
```

#### 长时间测试
```bash
python run_multi_account_test.py --long
```

#### 压力测试
```bash
python run_multi_account_test.py --stress
```

#### 自定义参数测试
```bash
python run_multi_account_test.py --custom \
    --accounts 4 \
    --rounds 20 \
    --tx-per-round 5 \
    --duration 60 \
    --balance 10000 \
    --min-amount 100 \
    --max-amount 500
```

### 3. 直接运行核心测试
```bash
python multi_account_integration_test.py
```

## ⚙️ 测试配置

### TestConfig参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `num_accounts` | 3 | 账户节点数量 |
| `num_transaction_rounds` | 5 | 每个账户的交易轮数 |
| `transactions_per_round` | 3 | 每轮交易的笔数 |
| `block_interval` | 2.0 | 区块生成间隔（秒） |
| `transaction_interval` | 0.5 | 交易间隔（秒） |
| `test_duration` | 30 | 总测试时长（秒） |
| `base_balance` | 10000 | 账户初始余额 |
| `transaction_amount_range` | (10, 500) | 交易金额范围 |

### 预设测试模式

| 模式 | 账户数 | 时长 | 交易轮数 | 说明 |
|------|--------|------|----------|------|
| `--quick` | 2 | 10秒 | 3 | 快速验证基本功能 |
| `--long` | 5 | 2分钟 | 50 | 中等规模稳定性测试 |
| `--stress` | 10 | 5分钟 | 100 | 高负载压力测试 |

## 📊 测试流程

### 1. 初始化阶段
- 生成测试账户（包含真实密钥对）
- 为每个账户初始化创世余额
- 启动四个进程（1个共识节点 + 3个账户节点）

### 2. 交易阶段
- 账户节点随机生成交易
- 交易通过安全签名验证
- 提交到共享交易池

### 3. 共识阶段
- 主链节点定期打包交易
- 生成新区块和默克尔证明
- 广播区块信息给所有账户节点

### 4. 更新阶段
- 账户节点接收区块信息
- 使用VPBManager更新本地VPB状态
- 验证交易完成情况

### 5. 评估阶段
- 统计测试数据
- 验证评判条件
- 生成测试报告

## ✅ 测试评判条件

### 必要条件（必须满足）
1. ✅ 交易正确生成、签名并提交到交易池
2. ✅ 主链节点正确打包交易，生成新区块
3. ✅ 账户节点正确接收区块信息，更新VPB
4. ✅ 系统无异常崩溃，交易金额正确

### 性能指标
- **交易成功率** > 80%
- **系统稳定性评分** > 70分
- **错误数量** = 0（理想情况）

## 📈 性能指标说明

| 指标 | 说明 | 优秀值 | 良好值 | 需改进 |
|------|------|--------|--------|--------|
| 交易吞吐量 (TPS) | 每秒处理的交易数 | >10 | >5 | ≤5 |
| 区块生成率 (BPS) | 每秒生成的区块数 | >0.5 | >0.3 | ≤0.3 |
| 交易成功率 | 成功交易/总交易 | >95% | >80% | ≤80% |
| 系统稳定性 | 基于错误率和成功率 | >90 | >70 | ≤70 |
| VPB更新效率 | 每秒VPB更新次数 | >5 | >2 | ≤2 |

## 🔧 使用示例

### 基本使用
```python
from multi_account_integration_test import TestConfig, run_multi_account_integration_test

# 创建配置
config = TestConfig(
    num_accounts=3,
    test_duration=60,
    base_balance=5000
)

# 运行测试
stats = run_multi_account_integration_test(config)
print(f"测试完成，成功率: {stats.success_rate:.2f}%")
```

### 自定义分析
```python
from test_analyzer import TestAnalyzer

# 创建分析器
analyzer = TestAnalyzer()

# 分析测试结果
report = analyzer.analyze_test_results(config, stats)

# 生成报告
analyzer.save_report(report)
```

## 🐛 常见问题

### Q: 测试运行时出现进程卡死怎么办？
A: 按Ctrl+C中断测试，程序会自动清理进程和临时文件。

### Q: 如何修改测试参数？
A: 使用`--custom`模式配合具体参数，或直接修改`TestConfig`类。

### Q: 测试数据保存在哪里？
A: 默认保存在临时目录，测试结束后自动清理。可通过`--temp-dir`指定目录。

### Q: 如何查看详细的测试日志？
A: 日志会输出到控制台，包含各进程的详细操作记录。

### Q: 测试失败如何排查？
A: 查看日志中的错误信息，重点关注：
- 交易验证失败原因
- VPB更新错误
- 进程间通信问题

## 📋 测试检查清单

运行测试前，请确认：

- [ ] 项目依赖已正确安装
- [ ] 所有核心模块可以正常导入
- [ ] 系统支持多进程操作
- [ ] 有足够的磁盘空间（建议>1GB）
- [ ] 没有其他程序占用测试端口

测试完成后，请检查：

- [ ] 所有进程正常退出
- [ ] 临时文件已清理
- [ ] 测试报告已生成
- [ ] 性能指标符合预期
- [ ] 无异常错误记录

## 🔄 持续改进

本测试系统持续改进中，欢迎：

1. **报告问题**：发现bug请及时报告
2. **功能建议**：提出新的测试场景
3. **性能优化**：提供测试效率优化建议
4. **文档完善**：补充使用说明和示例

## 📞 技术支持

如需技术支持或有疑问，请：

1. 查看本README文档
2. 检查代码中的详细注释
3. 查看生成的测试日志
4. 分析测试报告中的建议

---

**注意**：本测试系统仅用于验证EZChain项目各模块的集成正确性，不适用于生产环境部署。