# EZChain VPB Updater Design Document

**Version**: 1.0
**Date**: 2025/11/20
**Author**: EZChain Team

## Executive Summary

本文档基于Ezchain-py实验室版项目代码，设计商业化VPB更新器系统。VPB Updater负责在节点正常操作过程中（如执行其他交易），对本地的VPB数据进行实时更新和维护，确保数据的一致性和完整性。

VPB Architecture：

VPB（Validator Proof Block）采用**Value-Proofs-BlockIndex**三元组架构：

- **Value (V)**: 代表数字资产，包含连续整数范围
  - `begin_index`: 值范围的起始点
  - `end_index`: 值范围的结束点
  - `value_num`: 值单位数量
  - `state`: 交易状态（UNSPENT, SELECTED, COMMITTED, CONFIRMED）

- **Proofs (P)**: 用于交易验证的密码学证明单元
  - 包含`ProofUnit`对象，配备Merkle树证明
  - 每个`ProofUnit`包含：所有者地址、交易数据、Merkle证明
  - 支持多交易证明和引用计数

- **BlockIndex (B)**: 区块高度跟踪和所有权历史
  - `index_lst`: 区块高度的有序列表
  - `owner_data`: 映射到区块高度的所有权转移历史
  - 维护时间顺序的所有权记录

何时更新？
对于任意一个账户节点，其在进行交易时，则会触发（调用）VPB Updater用于跟新本地的所有value的Proofs和BlockIndex。原因在于，账户节点的任何交易都会影响其手头的所有value的Proofs和BlockIndex。

案例demo：
alice手头有4个value：value_1、value_2、value_3、value_4，它们也有对应的Proofs和BlockIndex。
当alice在高度h的区块提交了一笔新交易txns（假设为：alice->bob,value_2）时（这里txns为MultiTransactions类，txns在高度h的区块中的默克尔树根证明为mt_proof），alice就需要为其所有value，均添加相应的新增ProofUnit和index_lst、owner_data等。
具体地:
value_1在原本的Proofs上添加一个新的ProofUnit={txns, mt_proof};在原本的BlockIndex的index_lst添加一个新元素[h];原本的BlockIndex的owner_data不修改（因为转移的值是value_2,不是value_1）。
value_2在原本的Proofs上添加一个新的ProofUnit={txns, mt_proof};在原本的BlockIndex的index_lst添加一个新元素[h];在原本的BlockIndex的owner_data添加一个新元素(h, alice_addr)。
value_3在原本的Proofs上添加一个新的ProofUnit={txns, mt_proof};在原本的BlockIndex的index_lst添加一个新元素[h];原本的BlockIndex的owner_data不修改（因为转移的值是value_2,不是value_3）。
value_4在原本的Proofs上添加一个新的ProofUnit={txns, mt_proof};在原本的BlockIndex的index_lst添加一个新元素[h];原本的BlockIndex的owner_data不修改（因为转移的值是value_2,不是value_4）。

注意：上述的案例是示例，非严格的代码实现（例如：ProofUnit={txns, mt_proof}）。ProofUnit及BlockIndex在本项目中的实现可能和上述案例有些许差异，请根据上述的案例的核心思想，用本项目已实现的具体代码，进行融合。

在实现VPB Updater时，注意需对外提供调用vpb更新的接口，以方便账户节点在进行交易时触发（调用）VPB Updater用于跟新本地的所有value的Proofs和BlockIndex。