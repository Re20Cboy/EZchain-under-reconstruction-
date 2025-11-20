# EZChain VPB Updater

EZChain VPB (Verifiable Proof Block) 更新器，负责在节点正常操作过程中实时更新和维护VPB数据。

## 核心功能

- **实时VPB更新**: 交易时自动更新所有本地VPB的Proofs和BlockIndex
- **账户节点集成**: 简化账户节点的VPB更新流程
- **区块链级协调**: 支持多账户批量VPB更新
- **线程安全**: 支持并发操作

## 快速开始

### 基本使用

```python
from EZ_VPB_Updater import VPBUpdater, create_vpb_update_request

# 初始化VPB更新器
vpb_updater = VPBUpdater()

# 创建更新请求
request = create_vpb_update_request(
    account_address="0xalice1234567890abcdef",
    transaction=multi_transaction,
    block_height=1000,
    merkle_proof=merkle_proof
)

# 执行更新
result = vpb_updater.update_vpb_for_transaction(request)
```

### 账户节点集成

```python
from EZ_VPB_Updater import AccountNodeVPBIntegration

# 初始化账户节点集成
alice_integration = AccountNodeVPBIntegration("0xalice1234567890abcdef")

# 处理交易（自动VPB更新）
result = alice_integration.process_transaction(
    transaction=multi_transaction,
    block=block,
    merkle_proof=merkle_proof
)
```

## 运行测试和示例

```bash
# 运行测试
python -c "
import sys, os
sys.path.append(os.path.dirname(__file__))
from vpb_updater import VPBUpdaterFactory
print('VPB Updater initialized successfully')
"

# 运行基本示例
python -c "
import sys, os
sys.path.append(os.path.dirname(__file__))
from vpb_updater import VPBUpdaterFactory
from mock_components import Transaction, MultiTransactions, MerkleTreeProof

# 基本示例
vpb_updater = VPBUpdaterFactory.create_test_vpb_updater()
txn = Transaction('0xalice', '0xbob', 100, 1, 1)
multi_txn = MultiTransactions('0xalice', [txn])
proof = MerkleTreeProof('root', 'proof', 0)

from vpb_updater import create_vpb_update_request
request = create_vpb_update_request('0xalice', multi_txn, 100, proof)
result = vpb_updater.update_vpb_for_transaction(request)
print(f'Update successful: {result.success}')
"
```

## 架构

VPB采用Value-Proofs-BlockIndex三元组架构：
- **Value**: 数字资产，表示连续整数范围
- **Proofs**: 交易验证的密码学证明单元
- **BlockIndex**: 区块高度跟踪和所有权历史

当账户节点执行交易时，VPB Updater会：
1. 为所有该账户拥有的value添加新的ProofUnit
2. 更新BlockIndex的index_lst和owner_data
3. 持久化更新到存储

## 性能

- 单次更新: < 100ms
- 批量处理: > 1000 更新/秒
- 内存使用: < 1KB/VPB更新

## 许可证

EZChain项目的一部分，详见主项目许可证。