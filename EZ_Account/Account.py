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
from typing import Any, Dict, List, Optional

# Core EZChain imports - VPB system is the primary interface
from EZ_VPB import Value, ValueState
from EZ_VPB.VPBManager import VPBManager
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Tool_Box.SecureSignature import secure_signature_handler


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
                 name: Optional[str] = None):
        """
        Initialize an EZChain account with VPBManager.

        Args:
            address: Account address (identifier)
            private_key_pem: PEM encoded private key for signing
            public_key_pem: PEM encoded public key for verification
            name: Optional human-readable name for the account
        """
        self.address = address
        self.name = name or f"Account_{address[:8]}"
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem

        # VPB管理 - VPBManager是唯一的VPB操作接口
        self.vpb_manager = VPBManager(address)
        self._lock = threading.RLock()

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

        print(f"Account {self.name} ({address}) initialized with VPBManager")

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

    def update_after_transaction_sent(self, target_value: Value, confirmed_multi_txns,
                                     mt_proof, block_height: int, recipient_address: str) -> bool:
        """
        作为sender发送交易后更新VPB

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
                success = self.vpb_manager.update_after_transaction_sent(
                    target_value, confirmed_multi_txns, mt_proof,
                    block_height, recipient_address
                )
                if success:
                    self.last_activity = datetime.now()
                return success
            except Exception as e:
                print(f"发送交易后更新VPB失败: {e}")
                return False

    def receive_vpb_from_others(self, received_value, received_proof_units, received_block_index) -> bool:
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
                if success:
                    self.last_activity = datetime.now()
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

    # ========== 交易创建和管理接口 ==========

    def create_batch_transactions(self, transaction_requests: List[Dict],
                                reference: Optional[str] = None) -> Optional[Dict]:
        """
        批量创建交易

        Args:
            transaction_requests: 交易请求列表
            reference: 可选的参考标识

        Returns:
            多交易结果字典
        """
        try:
            multi_transaction_result = self.transaction_creator.create_multi_transactions(
                transaction_requests=transaction_requests,
                private_key_pem=self.private_key_pem
            )

            if multi_transaction_result:
                self._record_multi_transaction(multi_transaction_result, "batch_created", reference)
                multi_txn_hash = multi_transaction_result["multi_transactions"].digest
                print(f"批量交易创建成功: {multi_txn_hash[:16] if multi_txn_hash else 'N/A'}...")
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

    def submit_multi_transaction(self, multi_txn_result: Dict, transaction_pool=None) -> bool:
        """提交多交易到交易池"""
        try:
            if transaction_pool is not None:
                success, message = self.transaction_creator.submit_to_transaction_pool(
                    multi_txn_result, transaction_pool, self.public_key_pem
                )
                if success:
                    self._record_multi_transaction(multi_txn_result, "submitted")
                    print(f"多交易已提交: {message}")
                    self.last_activity = datetime.now()
                return success
            else:
                # 模拟提交
                multi_txn = multi_txn_result["multi_transactions"]
                print(f"多交易准备网络提交: {multi_txn.digest[:16] if multi_txn.digest else 'N/A'}...")
                self._record_multi_transaction(multi_txn_result, "submitted")
                return True
        except Exception as e:
            print(f"提交多交易失败: {e}")
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
                'selected': self.get_balance(ValueState.SELECTED),
                'local_committed': self.get_balance(ValueState.LOCAL_COMMITTED)
            },
            'values_count': len(self.get_values()),
            'vpb_summary': self.get_vpb_summary(),
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'transaction_history_count': len(self.transaction_history)
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

    def __del__(self):
        """析构函数"""
        self.cleanup()


# ========== 使用示例 ==========

"""
# 创建账户
account = Account(
    address="user_address_123",
    private_key_pem=private_key_bytes,
    public_key_pem=public_key_bytes,
    name="TestAccount"
)

# 从创世块初始化
genesis_value = Value("0x1000", 1000)
genesis_proof_units = []  # ProofUnit列表
genesis_block_index = BlockIndexList([0], owner="user_address_123")

account.initialize_from_genesis(genesis_value, genesis_proof_units, genesis_block_index)

# 查询余额
balance = account.get_available_balance()
print(f"可用余额: {balance}")

# 获取账户信息
info = account.get_account_info()
print(f"账户信息: {info}")

# 创建交易
transaction_requests = [
    {'recipient': 'recipient_456', 'amount': 100}
]

result = account.create_batch_transactions(transaction_requests)
if result:
    account.confirm_multi_transaction(result)

# 验证完整性
is_valid = account.validate_integrity()
print(f"账户完整性: {is_valid}")
"""