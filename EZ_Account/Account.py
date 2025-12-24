"""
EZChain Account Node Implementation

This module implements the core account node functionality for the EZChain blockchain system.
The account manages VPBs (Value-Proofs-BlockIndex) through the VPBManager interface,
creates transactions, and participates in the distributed validation network.

Key Features:
- Unified VPB management through VPBManager interface
- Transaction creation and signing
- Value state management
- Complete integration with modern EZChain VPB architecture
"""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

# Import CheckPoint for type hints
if TYPE_CHECKING:
    try:
        from EZ_CheckPoint.CheckPoint import CheckPointRecord
    except ImportError:
        CheckPointRecord = Any

# Core EZChain imports - VPB system is the primary interface
from EZ_VPB import Value, ValueState
from EZ_VPB.VPBManager import VPBManager
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_CheckPoint.CheckPoint import CheckPoint
from EZ_VPB_Validator.vpb_validator import VPBValidator

class Account:
    """
    EZChain Account Node

    Represents an account/wallet in the EZChain blockchain system. Each account manages
    its VPBs (Value-Proofs-BlockIndex) through the VPBManager interface.

    Design Principles:
    - All VPB operations go through VPBManager
    - Transaction creation uses CreateMultiTransactions
    - Thread-safe operations with proper locking
    - Clean separation of concerns
    """

    def __init__(self, address: str, private_key_pem: bytes, public_key_pem: bytes,
                 name: Optional[str] = None, data_directory: Optional[str] = None):
        """
        Initialize an EZChain account with VPBManager.

        Args:
            address: Account address (identifier)
            private_key_pem: PEM encoded private key for signing
            public_key_pem: PEM encoded public key for verification
            name: Optional human-readable name for the account
            data_directory: Optional custom data directory for storing account data
        """
        self.address = address
        self.name = name or f"Account_{address[:8]}"
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem

        # VPB管理 - VPBManager是唯一的VPB操作接口，支持自定义数据目录
        self.vpb_manager = VPBManager(address, data_directory=data_directory)
        self._lock = threading.RLock()

        # CheckPoint管理 - 为账户提供检查点功能，支持自定义数据目录
        checkpoint_db_path = f"ez_checkpoint_{address}.db" if not data_directory else f"{data_directory}/ez_checkpoint_{address}.db"
        self.checkpoint_manager = CheckPoint(checkpoint_db_path)

        # VPBValidator - 为账户提供VPB验证功能，传入checkpoint管理器
        self.vpb_validator = VPBValidator(checkpoint=self.checkpoint_manager)

        # CreateMultiTransactions for transaction creation
        self.transaction_creator = CreateMultiTransactions(
            address,
            self.vpb_manager.value_collection
        )

        # Account metadata
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

        # Security: Use secure signature handler
        self.signature_handler = secure_signature_handler

        # Transaction history tracking
        self.transaction_history: List[Dict] = []
        self.history_lock = threading.RLock()

        # Submitted transactions queue - tracks transactions submitted to tx pool
        # Structure: {multi_tx_hash: multi_tx_data}
        self.submitted_transactions: Dict[str, Any] = {}
        self.submitted_tx_lock = threading.RLock()

        # 精简输出: print(f"Account {self.name} ({address}) initialized with VPBManager")

    # ========== VPB管理接口（通过VPBManager） ==========

    def initialize_from_genesis(self, genesis_value: Value, genesis_proof_units: List,
                                genesis_block_index) -> bool:
        """
        从创世块初始化VPB

        Args:
            genesis_value: 创世Value
            genesis_proof_units: 创世ProofUnits列表
            genesis_block_index: 创世BlockIndex

        Returns:
            初始化成功返回True
        """
        with self._lock:
            try:
                success = self.vpb_manager.initialize_from_genesis(
                    genesis_value, genesis_proof_units, genesis_block_index
                )
                if success:
                    self.last_activity = datetime.now()
                return success
            except Exception as e:
                print(f"创世初始化失败: {e}")
                return False

    def update_vpb_after_transaction_sent(self, confirmed_multi_txns,
                                     mt_proof, block_height: int, recipient_address: str) -> bool:
        """
        作为sender发送交易后更新VPB（使用新的批量处理接口）

        Args:
            confirmed_multi_txns: 已确认的多笔交易
            mt_proof: 默克尔树证明
            block_height: 区块高度
            recipient_address: 主要接收方地址（单接收者场景）或默认接收者

        Returns:
            更新成功返回True
        """
        with self._lock:
            try:
                success = self.vpb_manager.update_after_transaction_sent(
                    confirmed_multi_txns, mt_proof,
                    block_height, recipient_address
                )

                if success:
                    # 将所有交易的所有Value状态置为ONCHAIN（通过VPBManager更新索引）
                    all_values = []
                    for txn in confirmed_multi_txns.multi_txns:
                        all_values.extend(txn.value)

                    updated_count = self.vpb_manager.update_values_state(all_values, ValueState.ONCHAIN)
                    print(f"Set {updated_count} transaction values to ONCHAIN state")
                    self.last_activity = datetime.now()

                return success
            except Exception as e:
                print(f"发送交易后更新VPB失败: {e}")
                return False

    def update_vpb_after_transaction_sent_legacy(self, target_value: Value, confirmed_multi_txns,
                                     mt_proof, block_height: int, recipient_address: str) -> bool:
        """
        作为sender发送交易后更新VPB（旧接口，已弃用）

        Args:
            target_value: 被转移的Value
            confirmed_multi_txns: 已确认的多笔交易
            mt_proof: 默克尔树证明
            block_height: 区块高度
            recipient_address: 接收方地址

        Returns:
            更新成功返回True
        """
        with self._lock:
            try:
                success = self.vpb_manager._old_update_after_transaction_sent(
                    target_value, confirmed_multi_txns, mt_proof,
                    block_height, recipient_address
                )
                if success:
                    self.last_activity = datetime.now()
                return success
            except Exception as e:
                print(f"发送交易后更新VPB失败: {e}")
                return False

    def receive_vpb_from_others(self, received_value: Value, received_proof_units: List[ProofUnit],
                                received_block_index: BlockIndexList) -> bool:
        """
        作为receiver接收其他账户发送的VPB

        Args:
            received_value: 接收到的Value
            received_proof_units: 接收到的ProofUnits
            received_block_index: 接收到的BlockIndex

        Returns:
            接收成功返回True
        """
        with self._lock:
            try:
                success = self.vpb_manager.receive_vpb_from_others(
                    received_value, received_proof_units, received_block_index
                )
                return success
            except Exception as e:
                print(f"接收VPB失败: {e}")
                return False

    # ========== 余额和Value查询接口 ==========

    def get_balance(self, state: ValueState = ValueState.UNSPENT) -> int:
        """
        获取指定状态的余额

        Args:
            state: Value状态

        Returns:
            余额
        """
        return self.vpb_manager.value_collection.get_balance_by_state(state)

    def get_available_balance(self) -> int:
        """获取可用余额"""
        return self.vpb_manager.get_unspent_balance()

    def get_total_balance(self) -> int:
        """获取总余额"""
        return self.vpb_manager.get_total_balance()

    def print_values_summary(self, title: Optional[str] = None) -> None:
        """
        简洁美观地打印所有Value信息摘要

        Args:
            title: 可选的自定义标题，默认使用账户名称
        """
        if title is None:
            title = f"{self.name} Values Summary"
        self.vpb_manager.print_all_values_summary(title)

    def get_values(self, state: Optional[ValueState] = None) -> List[Value]:
        """
        获取Value列表

        Args:
            state: 可选的状态过滤器

        Returns:
            Value列表
        """
        if state is None:
            return self.vpb_manager.get_all_values()
        return self.vpb_manager.value_collection.find_by_state(state)

    def get_unspent_values(self) -> List[Value]:
        """获取未花销的Value列表"""
        return self.vpb_manager.get_unspent_values()

    # ========== VPB查询接口 ==========

    def get_proof_units_for_value(self, value: Value) -> List:
        """获取指定Value的所有ProofUnits"""
        return self.vpb_manager.get_proof_units_for_value(value)

    def get_block_index_for_value(self, value: Value):
        """获取指定Value的BlockIndex"""
        return self.vpb_manager.get_block_index_for_value(value)

    def get_vpb_summary(self) -> Dict[str, Any]:
        """获取VPB摘要信息"""
        return self.vpb_manager.get_vpb_summary()

    def validate_vpb_integrity(self) -> bool:
        """验证VPB完整性"""
        return self.vpb_manager.validate_vpb_integrity()

    # ========== CheckPoint管理接口 ==========

    def create_checkpoint(self, value: Value, block_height: int) -> bool:
        """为Value创建检查点"""
        return self.checkpoint_manager.create_checkpoint(value, self.address, block_height)

    def update_checkpoint(self, value: Value, new_block_height: int) -> bool:
        """更新Value的检查点"""
        return self.checkpoint_manager.update_checkpoint(value, self.address, new_block_height)

    def find_containing_checkpoint(self, value: Value):
        """查找包含给定Value的checkpoint"""
        return self.checkpoint_manager.find_containing_checkpoint(value)

    def list_my_checkpoints(self):
        """查找当前地址的所有checkpoint"""
        return self.checkpoint_manager.find_checkpoints_by_owner(self.address)

    def list_all_checkpoints(self):
        """列出所有checkpoint"""
        return self.checkpoint_manager.list_all_checkpoints()

    def verify_vpb(self, value: Value, proof_units: List, block_index_list, main_chain_info) -> Any:
        """
        验证VPB三元组的完整性和合法性

        Args:
            value: 待验证的Value对象
            proof_units: 对应的ProofUnit列表
            block_index_list: 对应的BlockIndexList对象
            main_chain_info: 主链信息

        Returns:
            VPBVerificationReport: 详细的验证报告
        """
        # 执行验证
        verification_report = self.vpb_validator.verify_vpb_pair(
            value, proof_units, block_index_list, main_chain_info, self.address
        )

        # 如果验证通过，将待验证的value状态置为VERIFIED
        if verification_report.is_valid:
            try:
                value.set_state(ValueState.VERIFIED)
                print(f"VPB verification passed - Set value {value.begin_index} (amount: {value.value_num}) to VERIFIED state")
                self.last_activity = datetime.now()
            except Exception as e:
                print(f"Warning: Failed to set VERIFIED state for value {value.begin_index}: {e}")

        return verification_report

    def get_verification_stats(self) -> Dict[str, Any]:
        """获取VPB验证统计信息"""
        return self.vpb_validator.get_verification_stats()

    def reset_verification_stats(self):
        """重置VPB验证统计信息"""
        self.vpb_validator.reset_stats()

    # ========== 交易创建和管理接口 ==========

    def create_batch_transactions(self, transaction_requests: List[Dict],
                                reference: Optional[str] = None,
                                checkpoint: Optional['CheckPointRecord'] = None) -> Optional[Dict]:
        """
        批量创建交易

        Args:
            transaction_requests: 交易请求列表，每个请求可以包含：
                - recipient: 接收方地址
                - amount: 金额
                - checkpoint: 可选的检查点记录（用于特定交易的检查点优化）
            reference: 可选的参考标识
            checkpoint: 全局检查点记录，应用于所有未指定检查点的交易

        Returns:
            多交易结果字典
        """
        try:
            multi_transaction_result = self.transaction_creator.create_multi_transactions(
                transaction_requests=transaction_requests,
                private_key_pem=self.private_key_pem,
                checkpoint=checkpoint
            )

            if multi_transaction_result:
                # 将所有使用的Value状态置为PENDING（通过VPBManager更新索引）
                with self._lock:
                    # 设置selected_values的状态为PENDING
                    self.vpb_manager.update_values_state(
                        multi_transaction_result.get("selected_values", []),
                        ValueState.PENDING
                    )

                    # 新设计：没有change_values，但仍保持兼容性
                    change_values = multi_transaction_result.get("change_values", [])
                    if change_values:
                        self.vpb_manager.update_values_state(
                            change_values,
                            ValueState.PENDING
                        )

                self._record_multi_transaction(multi_transaction_result, "batch_created", reference)
                return multi_transaction_result
            else:
                print("批量交易创建失败")
                return None

        except Exception as e:
            print(f"创建批量交易失败: {e}")
            return None

    def confirm_multi_transaction(self, multi_txn_result: Dict) -> bool:
        """确认多交易"""
        try:
            success = self.transaction_creator.confirm_multi_transactions(multi_txn_result)
            if success:
                self._record_multi_transaction(multi_txn_result, "confirmed")
                print("多交易已确认")
                self.last_activity = datetime.now()
            return success
        except Exception as e:
            print(f"确认多交易失败: {e}")
            return False

    def create_submit_tx_info(self, multi_txn_result: Dict) -> Optional[SubmitTxInfo]:
        """
        将multi_transaction(通过create_batch_transactions获得)转化为SubmitTxInfo

        Args:
            multi_txn_result: 通过create_batch_transactions获得的多交易结果字典

        Returns:
            SubmitTxInfo: 生成的SubmitTxInfo实例，失败返回None
        """
        try:
            # 从multi_txn_result中获取MultiTransactions对象
            multi_transactions = multi_txn_result.get("multi_transactions")
            if not multi_transactions:
                print("multi_txn_result中缺少multi_transactions")
                return None

            # 使用SubmitTxInfo的工厂方法创建SubmitTxInfo
            submit_tx_info = SubmitTxInfo.create_from_multi_transactions(
                multi_transactions=multi_transactions,
                private_key_pem=self.private_key_pem,
                public_key_pem=self.public_key_pem
            )

            # 记录创建SubmitTxInfo的操作
            self._record_multi_transaction(multi_txn_result, "submit_info_created")

            multi_txn_hash = multi_transactions.digest
            # 精简输出: print(f"SubmitTxInfo创建成功: {multi_txn_hash[:16] if multi_txn_hash else 'N/A'}...")
            self.last_activity = datetime.now()

            return submit_tx_info

        except Exception as e:
            print(f"创建SubmitTxInfo失败: {e}")
            return None

    def submit_tx_infos_to_pool(self, submit_tx_info: SubmitTxInfo, tx_pool, multi_txn_result: Dict = None) -> bool:
        """
        提交SubmitTxInfo至交易池，并同步添加到本地提交队列

        Args:
            submit_tx_info: 要提交的SubmitTxInfo
            tx_pool: 交易池实例
            multi_txn_result: 原始的多交易结果字典（可选）

        Returns:
            bool: 提交成功返回True，失败返回False
        """
        try:
            # 提交到交易池
            success, message = tx_pool.add_submit_tx_info(submit_tx_info)

            if success:
                # 提交成功后，同步添加到本地队列
                multi_tx_hash = submit_tx_info.multi_transactions_hash

                # 获取多交易数据用于存储
                if multi_txn_result:
                    multi_tx_data = multi_txn_result.get("multi_transactions")
                else:
                    # 如果没有提供multi_txn_result，至少存储基本信息
                    multi_tx_data = {
                        'hash': multi_tx_hash,
                        'submit_timestamp': submit_tx_info.submit_timestamp,
                        'submitter': submit_tx_info.submitter_address,
                        'transaction_count': getattr(multi_tx_data, 'transaction_count', 'unknown') if multi_tx_data else 'unknown',
                        'total_amount': getattr(multi_tx_data, 'total_amount', 'unknown') if multi_tx_data else 'unknown'
                    }

                self._add_to_submitted_queue(multi_tx_hash, multi_tx_data)

                # 精简输出: print(f"交易已成功提交至交易池并添加到本地队列: {multi_tx_hash[:16]}...")
                self.last_activity = datetime.now()
                return True
            else:
                print(f"提交交易至交易池失败: {message}")
                return False

        except Exception as e:
            print(f"提交交易失败: {e}")
            return False

    # ========== 账户信息和管理接口 ==========

    def get_account_info(self) -> Dict:
        """获取账户信息"""
        return {
            'address': self.address,
            'name': self.name,
            'balances': {
                'total': self.get_total_balance(),
                'available': self.get_available_balance(),
                'unspent': self.get_balance(ValueState.UNSPENT),
                'confirmed': self.get_balance(ValueState.CONFIRMED),
            },
            'values_count': len(self.get_values()),
            'vpb_summary': self.get_vpb_summary(),
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'transaction_history_count': len(self.transaction_history),
            'submitted_transactions_count': self.get_submitted_transactions_count()
        }

    def validate_integrity(self) -> bool:
        """验证账户数据完整性"""
        try:
            # 验证VPB完整性
            if not self.validate_vpb_integrity():
                print("VPB完整性验证失败")
                return False

            # 验证ValueCollection完整性
            if not self.vpb_manager.value_collection.validate_integrity():
                print("ValueCollection完整性验证失败")
                return False

            return True
        except Exception as e:
            print(f"完整性验证出错: {e}")
            return False

    def clear_all_data(self) -> bool:
        """清除所有数据"""
        try:
            with self._lock:
                success = self.vpb_manager.clear_all_data()
                if success:
                    # 清除交易历史
                    with self.history_lock:
                        self.transaction_history.clear()
                    # 清除提交交易队列
                    self.clear_submitted_transactions()
                    print(f"已清除{self.name}的所有数据")
                    self.last_activity = datetime.now()
                return success
        except Exception as e:
            print(f"清除数据失败: {e}")
            return False

    def cleanup(self):
        """清理资源"""
        try:
            self.clear_all_data()
            self.signature_handler.clear_key()
            if hasattr(self, 'checkpoint_manager'):
                self.checkpoint_manager.clear_cache()
            print(f"Account {self.name} 清理完成")
        except Exception as e:
            print(f"清理资源失败: {e}")

    # ========== 私有辅助方法 ==========

    def _record_multi_transaction(self, multi_txn_result: Dict, action: str,
                                reference: Optional[str] = None):
        """记录多交易历史"""
        try:
            with self.history_lock:
                multi_txn = multi_txn_result["multi_transactions"]
                history_entry = {
                    'hash': multi_txn.digest,
                    'action': action,
                    'timestamp': datetime.now().isoformat(),
                    'transaction_count': multi_txn_result['transaction_count'],
                    'total_amount': multi_txn_result['total_amount'],
                    'sender': self.address,
                    'reference': reference,
                    'type': 'multi_transaction'
                }
                self.transaction_history.append(history_entry)

                # 保留最近1000条记录
                if len(self.transaction_history) > 1000:
                    self.transaction_history = self.transaction_history[-1000:]
        except Exception as e:
            print(f"记录多交易历史失败: {e}")

    # ========== 提交交易队列管理方法 ==========

    def _add_to_submitted_queue(self, multi_tx_hash: str, multi_tx_data: Any) -> None:
        """
        添加多交易到本地提交队列

        Args:
            multi_tx_hash: 多交易哈希值，作为字典索引
            multi_tx_data: 多交易数据本身
        """
        try:
            with self.submitted_tx_lock:
                self.submitted_transactions[multi_tx_hash] = multi_tx_data
                # 精简输出: print(f"交易已添加到本地提交队列: {multi_tx_hash[:16]}...")
        except Exception as e:
            print(f"添加交易到本地队列失败: {e}")

    def remove_from_submitted_queue(self, multi_tx_hash: str) -> bool:
        """
        从本地提交队列中移除已确认的交易

        Args:
            multi_tx_hash: 要移除的多交易哈希值

        Returns:
            bool: 成功移除返回True，否则返回False
        """
        try:
            with self.submitted_tx_lock:
                if multi_tx_hash in self.submitted_transactions:
                    del self.submitted_transactions[multi_tx_hash]
                    print(f"已从本地队列移除已确认交易: {multi_tx_hash[:16]}...")
                    return True
                else:
                    print(f"本地队列中未找到交易: {multi_tx_hash[:16]}...")
                    return False
        except Exception as e:
            print(f"从本地队列移除交易失败: {e}")
            return False

    def get_submitted_transaction(self, multi_tx_hash: str) -> Optional[Any]:
        """
        从本地提交队列中获取交易数据

        Args:
            multi_tx_hash: 多交易哈希值

        Returns:
            多交易数据，如果不存在则返回None
        """
        try:
            with self.submitted_tx_lock:
                return self.submitted_transactions.get(multi_tx_hash)
        except Exception as e:
            print(f"获取本地队列交易失败: {e}")
            return None

    def get_all_submitted_transactions(self) -> Dict[str, Any]:
        """
        获取本地提交队列中的所有交易

        Returns:
            Dict: 包含所有提交交易的字典
        """
        try:
            with self.submitted_tx_lock:
                return self.submitted_transactions.copy()
        except Exception as e:
            print(f"获取本地队列失败: {e}")
            return {}

    def get_submitted_transactions_count(self) -> int:
        """
        获取本地提交队列中的交易数量

        Returns:
            int: 队列中的交易数量
        """
        try:
            with self.submitted_tx_lock:
                return len(self.submitted_transactions)
        except Exception as e:
            print(f"获取本地队列大小失败: {e}")
            return 0

    def clear_submitted_transactions(self) -> bool:
        """
        清空本地提交队列

        Returns:
            bool: 清空成功返回True，失败返回False
        """
        try:
            with self.submitted_tx_lock:
                self.submitted_transactions.clear()
                print("本地提交队列已清空")
                return True
        except Exception as e:
            print(f"清空本地队列失败: {e}")
            return False

    def __del__(self):
        """析构函数"""
        self.cleanup()
