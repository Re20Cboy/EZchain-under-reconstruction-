"""
主链共识节点
用于维护主链信息、管理交易池、生成区块和处理VPB数据更新
"""

import time
import hashlib
import random
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from threading import Thread, Lock
from collections import defaultdict

from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_VPB.values.Value import Value, ValueState
from EZ_VPB.proofs.ProofUnit import ProofUnit
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Units.MerkleProof import MerkleTreeProof

logger = logging.getLogger(__name__)


@dataclass
class TransactionPoolEntry:
    """交易池条目"""
    multi_transactions: MultiTransactions
    timestamp: float
    sender_address: str
    selected_values: List[Value]
    change_values: List[Value]
    priority: int = 0

    def __post_init__(self):
        if self.priority == 0:
            # 基于交易金额和手续费计算优先级
            total_amount = sum(txn.amount for txn in self.multi_transactions.multi_txns
                             if hasattr(txn, 'amount'))
            self.priority = int(total_amount + time.time())


@dataclass
class Block:
    """区块结构"""
    height: int
    previous_hash: str
    timestamp: float
    transactions: List[MultiTransactions]
    merkle_root: str
    miner: str
    nonce: int = 0

    def calculate_hash(self) -> str:
        """计算区块哈希"""
        block_data = f"{self.height}{self.previous_hash}{self.timestamp}{self.merkle_root}{self.nonce}"
        return hashlib.sha256(block_data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'height': self.height,
            'previous_hash': self.previous_hash,
            'timestamp': self.timestamp,
            'transactions': [tx.__dict__ for tx in self.transactions],
            'merkle_root': self.merkle_root,
            'miner': self.miner,
            'nonce': self.nonce
        }


class BlockchainNode:
    """主链共识节点"""

    def __init__(self, node_id: str = "main_node", mining_difficulty: int = 2):
        """
        初始化主链共识节点

        Args:
            node_id: 节点ID
            mining_difficulty: 挖矿难度（前导零数量）
        """
        self.node_id = node_id
        self.mining_difficulty = mining_difficulty

        # 交易池
        self.transaction_pool: List[TransactionPoolEntry] = []
        self.pool_lock = Lock()

        # 区块链
        self.blocks: List[Block] = []
        self.chain_lock = Lock()

        # 账户注册表
        self.registered_accounts: Dict[str, Any] = {}  # address -> Account object

        # 节点状态
        self.is_mining = False
        self.current_height = 0

        # 创世区块
        self._create_genesis_block()

        # 启动挖矿线程
        self.mining_thread = Thread(target=self._mining_loop, daemon=True)
        self.mining_thread.start()

        logger.info(f"区块链节点 {node_id} 初始化完成")

    def _create_genesis_block(self):
        """创建创世区块"""
        genesis_block = Block(
            height=0,
            previous_hash="0" * 64,
            timestamp=time.time(),
            transactions=[],
            merkle_root="",
            miner="genesis"
        )
        genesis_block.merkle_root = self._calculate_merkle_root([])

        with self.chain_lock:
            self.blocks.append(genesis_block)
            self.current_height = 0

        logger.info("创世区块已创建")

    def register_account(self, account: Any) -> bool:
        """
        注册账户到区块链节点

        Args:
            account: Account对象

        Returns:
            注册是否成功
        """
        try:
            address = account.address
            self.registered_accounts[address] = account
            logger.info(f"账户 {address} 已注册到区块链节点")
            return True
        except Exception as e:
            logger.error(f"注册账户失败: {e}")
            return False

    def submit_transaction(self, multi_transactions: MultiTransactions,
                          selected_values: List[Value],
                          change_values: List[Value],
                          sender_address: str) -> bool:
        """
        提交交易到交易池

        Args:
            multi_transactions: 多交易对象
            selected_values: 选中的value
            change_values: 找零value
            sender_address: 发送方地址

        Returns:
            提交是否成功
        """
        try:
            # 验证发送方账户是否已注册
            if sender_address not in self.registered_accounts:
                logger.error(f"发送方账户 {sender_address} 未注册")
                return False

            # 创建交易池条目
            pool_entry = TransactionPoolEntry(
                multi_transactions=multi_transactions,
                timestamp=time.time(),
                sender_address=sender_address,
                selected_values=selected_values,
                change_values=change_values
            )

            # 添加到交易池
            with self.pool_lock:
                self.transaction_pool.append(pool_entry)
                # 按优先级排序
                self.transaction_pool.sort(key=lambda x: x.priority, reverse=True)

            logger.info(f"交易已提交到交易池，发送方: {sender_address}, 交易数量: {len(multi_transactions.multi_txns)}")
            return True

        except Exception as e:
            logger.error(f"提交交易失败: {e}")
            return False

    def _calculate_merkle_root(self, transactions: List[MultiTransactions]) -> str:
        """计算交易的默克尔根"""
        if not transactions:
            return ""

        tx_hashes = []
        for tx in transactions:
            # 简化：使用交易哈希的字符串表示
            tx_str = str(tx.digest) if hasattr(tx, 'digest') else str(tx)
            tx_hashes.append(hashlib.sha256(tx_str.encode()).hexdigest())

        # 构建默克尔树
        while len(tx_hashes) > 1:
            next_level = []
            for i in range(0, len(tx_hashes), 2):
                if i + 1 < len(tx_hashes):
                    combined = tx_hashes[i] + tx_hashes[i+1]
                else:
                    combined = tx_hashes[i] + tx_hashes[i]  # 奇数个时复制最后一个
                next_level.append(hashlib.sha256(combined.encode()).hexdigest())
            tx_hashes = next_level

        return tx_hashes[0] if tx_hashes else ""

    def _mine_block(self, transactions: List[TransactionPoolEntry]) -> Optional[Block]:
        """挖矿生成新区块"""
        try:
            previous_block = self.blocks[-1]
            previous_hash = previous_block.calculate_hash()

            # 准备交易
            block_transactions = [entry.multi_transactions for entry in transactions]
            merkle_root = self._calculate_merkle_root(block_transactions)

            # 创建候选区块
            candidate_block = Block(
                height=self.current_height + 1,
                previous_hash=previous_hash,
                timestamp=time.time(),
                transactions=block_transactions,
                merkle_root=merkle_root,
                miner=self.node_id
            )

            # 挖矿（简化版PoW）
            target = "0" * self.mining_difficulty
            while candidate_block.calculate_hash()[:self.mining_difficulty] != target:
                candidate_block.nonce += 1
                if candidate_block.nonce > 100000:  # 简化挖矿过程
                    break

            # 检查是否找到有效哈希
            if candidate_block.calculate_hash()[:self.mining_difficulty] == target:
                logger.info(f"成功挖出区块 #{candidate_block.height}, 哈希: {candidate_block.calculate_hash()[:16]}...")
                return candidate_block
            else:
                logger.warning("挖矿失败，尝试下一个区块")
                return None

        except Exception as e:
            logger.error(f"挖矿过程出错: {e}")
            return None

    def _generate_merkle_proof(self, block: Block, transaction: MultiTransactions) -> MerkleTreeProof:
        """为交易生成默克尔树证明"""
        try:
            # 简化实现：创建基本的默克尔证明
            tx_hashes = []
            tx_index = -1

            for i, tx in enumerate(block.transactions):
                tx_str = str(tx.digest) if hasattr(tx, 'digest') else str(tx)
                tx_hash = hashlib.sha256(tx_str.encode()).hexdigest()
                tx_hashes.append(tx_hash)

                if tx == transaction:
                    tx_index = i

            # 创建简化的默克尔证明对象
            merkle_proof = MerkleTreeProof()
            if hasattr(merkle_proof, 'merkle_root'):
                merkle_proof.merkle_root = block.merkle_root
            if hasattr(merkle_proof, 'proof_path'):
                merkle_proof.proof_path = []  # 简化实现
            if hasattr(merkle_proof, 'leaf_index'):
                merkle_proof.leaf_index = tx_index

            return merkle_proof

        except Exception as e:
            logger.error(f"生成默克尔证明失败: {e}")
            return MerkleTreeProof()

    def _process_block_confirmations(self, block: Block, pool_entries: List[TransactionPoolEntry]):
        """处理区块确认，更新相关账户的VPB数据"""
        try:
            logger.info(f"开始处理区块 #{block.height} 的确认，包含 {len(pool_entries)} 笔交易")

            for entry in pool_entries:
                sender_account = self.registered_accounts.get(entry.sender_address)
                if not sender_account:
                    logger.warning(f"找不到发送方账户: {entry.sender_address}")
                    continue

                # 为每笔交易生成默克尔证明
                for multi_tx in entry.multi_transactions.multi_txns:
                    merkle_proof = self._generate_merkle_proof(block, entry.multi_transactions)

                    # 更新发送方的VPB数据
                    self._update_sender_vpb(
                        sender_account,
                        entry.selected_values,
                        entry.multi_transactions,
                        merkle_proof,
                        block.height
                    )

                # 更新接收方的VPB数据
                self._update_receivers_vpb(
                    entry.multi_transactions,
                    block.height
                )

            logger.info(f"区块 #{block.height} 的VPB更新处理完成")

        except Exception as e:
            logger.error(f"处理区块确认失败: {e}")

    def _update_sender_vpb(self, sender_account: Any, selected_values: List[Value],
                          confirmed_multi_txns: MultiTransactions, mt_proof: MerkleTreeProof,
                          block_height: int):
        """更新发送方的VPB数据"""
        try:
            # 选择第一个value作为目标value（简化实现）
            if selected_values:
                target_value = selected_values[0]

                # 确定接收方地址（简化实现）
                recipient_address = "unknown"
                if confirmed_multi_txns.multi_txns:
                    recipient_address = confirmed_multi_txns.multi_txns[0].recipient

                # 调用VPBManager的更新方法
                success = sender_account.vpb_manager.update_after_transaction_sent(
                    target_value=target_value,
                    confirmed_multi_txns=confirmed_multi_txns,
                    mt_proof=mt_proof,
                    block_height=block_height,
                    recipient_address=recipient_address
                )

                if success:
                    logger.debug(f"发送方 {sender_account.address} VPB更新成功")
                else:
                    logger.error(f"发送方 {sender_account.address} VPB更新失败")

        except Exception as e:
            logger.error(f"更新发送方VPB失败: {e}")

    def _update_receivers_vpb(self, multi_transactions: MultiTransactions, block_height: int):
        """更新接收方的VPB数据"""
        try:
            for tx in multi_transactions.multi_txns:
                recipient_address = tx.recipient
                recipient_account = self.registered_accounts.get(recipient_address)

                if not recipient_account:
                    continue

                # 为接收方创建新的value
                if hasattr(tx, 'amount') and hasattr(tx, 'value'):
                    # 如果有明确的金额，使用金额
                    amount = tx.amount
                    for value in tx.value:
                        new_value = Value(f"0x{10000 + block_height * 1000:04x}", amount, ValueState.UNSPENT)
                        block_index = BlockIndexList([block_height], owner=recipient_address)

                        success = recipient_account.vpb_manager.receive_vpb_from_others(
                            new_value, [], block_index
                        )

                        if success:
                            logger.debug(f"接收方 {recipient_address} 收到 {amount} 单位")
                        else:
                            logger.error(f"接收方 {recipient_address} 接收失败")

        except Exception as e:
            logger.error(f"更新接收方VPB失败: {e}")

    def _mining_loop(self):
        """挖矿循环"""
        while True:
            try:
                # 等待交易池中有交易
                with self.pool_lock:
                    if not self.transaction_pool:
                        time.sleep(1)
                        continue

                    # 选择交易进行打包（最多10笔）
                    transactions_to_mine = self.transaction_pool[:10]

                if not self.is_mining:
                    time.sleep(0.1)
                    continue

                # 挖矿
                self.is_mining = True
                new_block = self._mine_block(transactions_to_mine)
                self.is_mining = False

                if new_block:
                    # 添加到区块链
                    with self.chain_lock:
                        self.blocks.append(new_block)
                        self.current_height = new_block.height

                    # 从交易池中移除已打包的交易
                    with self.pool_lock:
                        for entry in transactions_to_mine:
                            if entry in self.transaction_pool:
                                self.transaction_pool.remove(entry)

                    # 处理VPB更新
                    self._process_block_confirmations(new_block, transactions_to_mine)

                time.sleep(1)  # 避免过度占用CPU

            except Exception as e:
                logger.error(f"挖矿循环出错: {e}")
                time.sleep(5)

    def get_chain_info(self) -> Dict[str, Any]:
        """获取区块链信息"""
        with self.chain_lock:
            return {
                'current_height': self.current_height,
                'total_blocks': len(self.blocks),
                'pool_size': len(self.transaction_pool),
                'registered_accounts': len(self.registered_accounts),
                'latest_block_hash': self.blocks[-1].calculate_hash() if self.blocks else None
            }

    def get_account_balance(self, address: str) -> int:
        """获取账户余额"""
        account = self.registered_accounts.get(address)
        if account:
            try:
                return account.vpb_manager.get_unspent_balance()
            except:
                return 0
        return 0

    def shutdown(self):
        """关闭节点"""
        self.is_mining = False
        logger.info(f"区块链节点 {self.node_id} 已关闭")