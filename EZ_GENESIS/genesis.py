"""
EZChain Genesis Block Generator

This module implements the creation of genesis blocks for the EZChain blockchain system.
The genesis block serves as the starting point of the blockchain and is responsible for
initial value distribution and establishing the initial global state.

Design Principles:
- Unified Genesis Architecture: Single MultiTransactions and single SubmitTxInfo for all accounts
- Single-Leaf Merkle Tree: Simplified verification with one hash leaf that equals the root
- Clean Interface: Streamlined API with consistent data flow
- Comprehensive VPB Support: Complete VPB data generation for all accounts

Core Features:
- Compatible with existing VPB verification system
- Follows EZChain transaction format standards
- Integrates with Account and MultiTransactions architecture
- Generates proper Merkle proofs and block indices
"""

import datetime
import hashlib
import json
import logging
from typing import List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from EZ_Account.Account import Account
    from EZ_VPB.values.Value import Value
    from EZ_VPB.proofs.ProofUnit import ProofUnit
    from EZ_VPB.block_index.BlockIndexList import BlockIndexList

# EZChain core imports
from EZ_Main_Chain.Block import Block
from EZ_VPB.block_index.BlockIndexList import BlockIndexList
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Transaction.CreateMultiTransactions import CreateMultiTransactions
from EZ_Transaction.SingleTransaction import Transaction
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Units.MerkleTree import MerkleTree, MerkleTreeNode
from EZ_Units.MerkleProof import MerkleTreeProof
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from .genesis_account import get_genesis_manager, GenesisAccountManager

# VPB imports
try:
    from EZ_VPB.values.Value import Value, ValueState
    from EZ_VPB.proofs.ProofUnit import ProofUnit
except ImportError:
    # Allow mocking in tests
    Value = None
    ValueState = None
    ProofUnit = None

# Configure logging
logger = logging.getLogger(__name__)

# Genesis constants
GENESIS_MINER = "genesis_miner"
GENESIS_BLOCK_INDEX = 0

# Default denomination configuration for initial value distribution
DEFAULT_DENOMINATION_CONFIG = [
    (100, 20),  # 100*20
    (50, 20),   # 50*20
    (20, 20),   # 20*20
    (10, 20),   # 10*20
    (5, 20),    # 5*20
    (1, 20)     # 1*20
]


class GenesisBlockCreator:
    """
    Genesis Block Creator for EZChain

    This class is responsible for creating unified genesis blocks that initialize
    the EZChain blockchain with a single MultiTransactions containing all initial
    value distributions for all accounts.
    """

    def __init__(self, denomination_config: Optional[List[Tuple[int, int]]] = None,
                 genesis_manager: Optional[GenesisAccountManager] = None):
        """
        Initialize the Genesis Block Creator

        Args:
            denomination_config: List of (amount, count) tuples for value distribution
            genesis_manager: Genesis account manager instance
        """
        self.denomination_config = denomination_config or DEFAULT_DENOMINATION_CONFIG
        self.genesis_timestamp = datetime.datetime.now()
        self.genesis_manager = genesis_manager or get_genesis_manager()

        # Calculate total initial value per account
        self.total_initial_value = sum(amount * count for amount, count in self.denomination_config)

        logger.info(f"Genesis creator initialized with total initial value: {self.total_initial_value} per account")
        logger.info(f"Genesis account address: {self.genesis_manager.get_genesis_address()}")

    def create_unified_genesis_block(self, accounts: List["Account"],
                                   custom_miner: Optional[str] = None) -> Tuple[Block, SubmitTxInfo, MultiTransactions, MerkleTree]:
        """
        Create a unified genesis block with single MultiTransactions and single SubmitTxInfo

        Args:
            accounts: List of Account objects to receive initial values
            custom_miner: Custom miner address (default: GENESIS_MINER)

        Returns:
            Tuple[Block, SubmitTxInfo, MultiTransactions, MerkleTree]:
            - The created genesis block
            - Single SubmitTxInfo containing all transactions
            - Unified MultiTransactions containing all accounts' transactions
            - Merkle tree with single leaf node
        """
        logger.info("🌟 ===== 开始创建统一创世块 ===== 🌟")

        if not accounts:
            raise ValueError("At least one account must be provided for genesis block")

        # Use genesis account as sender
        sender_address = self.genesis_manager.get_genesis_address()
        private_key_pem = self.genesis_manager.get_private_key_pem()
        public_key_pem = self.genesis_manager.get_public_key_pem()
        miner_address = custom_miner or GENESIS_MINER

        logger.info(f"为 {len(accounts)} 个账户创建统一创世块")
        logger.info(f"发送者: {sender_address}, 矿工: {miner_address}")
        logger.info(f"账户列表: {[acc.address for acc in accounts]}")

        # Step 1: Create unified MultiTransactions for all accounts
        logger.info("\n=== 步骤1: 创建统一MultiTransactions ===")
        unified_multi_txn = self._create_unified_genesis_transactions(accounts, sender_address)
        logger.info(f"统一MultiTransactions包含 {len(unified_multi_txn.multi_txns)} 个交易")

        # Step 2: Create single SubmitTxInfo for the unified MultiTransactions
        logger.info("\n=== 步骤2: 创建统一SubmitTxInfo ===")
        unified_submit_tx_info = SubmitTxInfo(unified_multi_txn, private_key_pem, public_key_pem)
        logger.info(f"统一SubmitTxInfo哈希: {unified_submit_tx_info.multi_transactions_hash}")

        # Step 3: Build single-leaf Merkle tree from SubmitTxInfo
        logger.info("\n=== 步骤3: 构建单叶子节点默克尔树 ===")
        merkle_tree = self._build_single_leaf_merkle_tree(unified_submit_tx_info)

        # Step 4: Create genesis block
        logger.info("\n=== 步骤4: 创建创世块 ===")
        merkle_root = merkle_tree.get_root_hash()
        logger.info(f"🌳 创世块默克尔树根: {merkle_root}")

        genesis_block = Block(
            index=GENESIS_BLOCK_INDEX,
            m_tree_root=merkle_root,
            miner=miner_address,
            pre_hash="0",  # Genesis block has no previous hash
            nonce=0,  # No mining needed for genesis
            time=self.genesis_timestamp
        )

        # Step 5: Add transaction submitter address to bloom filter
        logger.info("\n=== 步骤5: 添加提交者地址到布隆过滤器 ===")
        genesis_block.add_item_to_bloom(unified_submit_tx_info.submitter_address)
        logger.info(f"  已添加提交者地址到布隆过滤器: {unified_submit_tx_info.submitter_address}")

        logger.info("\n🎉 ===== 统一创世块创建完成 ===== 🎉")
        logger.info(f"  - 创世块索引: {genesis_block.index}")
        logger.info(f"  - 矿工地址: {genesis_block.miner}")
        logger.info(f"  - 前一个区块哈希: {genesis_block.pre_hash}")
        logger.info(f"  - 随机数 (nonce): {genesis_block.nonce}")
        logger.info(f"  - 时间戳: {genesis_block.time}")
        logger.info(f"  - 默克尔树根 (Merkle Root): {genesis_block.m_tree_root}")
        logger.info(f"  - 包含账户数量: {len(accounts)}")
        logger.info(f"  - 总交易数量: {len(unified_multi_txn.multi_txns)}")
        logger.info(f"  - 布隆过滤器大小: {len(genesis_block.bloom) if genesis_block.bloom else 'N/A'}")

        return genesis_block, unified_submit_tx_info, unified_multi_txn, merkle_tree

    def create_genesis_vpb_for_account(self, account_addr: str,
                                     genesis_block: Block,
                                     unified_submit_tx_info: SubmitTxInfo,
                                     unified_multi_txn: MultiTransactions,
                                     merkle_tree: MerkleTree) -> Tuple[List["Value"], List["ProofUnit"], BlockIndexList]:
        """
        Create complete VPB data for a single account from unified genesis block

        Args:
            account_addr: Account address string
            genesis_block: Genesis block containing the transaction
            unified_submit_tx_info: Unified SubmitTxInfo for ALL genesis transactions
            unified_multi_txn: Unified MultiTransactions containing ALL accounts' transactions
            merkle_tree: Merkle tree of the single genesis SubmitTxInfo

        Returns:
            Tuple[List[Value], List[ProofUnit], BlockIndexList]:
            - List of Value objects created from the account's transactions
            - List of ProofUnit objects containing the proofs for each value
            - BlockIndexList containing the block index information
        """
        logger.info(f"🔧 为账户 {account_addr} 创建创世VPB数据")

        # Create Merkle proof for the unified SubmitTxInfo (single genesis transaction)
        merkle_proof = self.create_merkle_proof_for_submit_tx_info(unified_submit_tx_info, merkle_tree)

        # Create block index for the account
        block_index = self.create_block_index(account_addr)

        # Create Value objects and corresponding ProofUnits for each transaction
        genesis_values = []
        genesis_proof_units = []

        if not unified_multi_txn or not unified_multi_txn.multi_txns:
            logger.error(f"统一MultiTransactions无效或为空")
            return [], [], block_index

        # Create Value and ProofUnit for transactions that belong to this account
        for txn in unified_multi_txn.multi_txns:
            try:
                # Extract Value information from transaction's value list
                if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                    # Each transaction should contain one Value object for genesis
                    for txn_value in txn.value:
                        if isinstance(txn_value, Value):
                            # Only process transactions that belong to this account (as recipient)
                            if hasattr(txn, 'recipient') and txn.recipient == account_addr:
                                # Extract genesis value from transaction
                                genesis_values.append(txn_value)

                                # Create ProofUnit for this value using the UNIFIED MultiTransactions and the SAME merkle proof
                                proof_unit = ProofUnit(
                                    owner=account_addr,
                                    owner_multi_txns=unified_multi_txn,  # Use the unified MultiTransactions
                                    owner_mt_proof=merkle_proof  # Use the same merkle proof for all values
                                )
                                genesis_proof_units.append(proof_unit)
                            else:
                                # Skip transactions that don't belong to this account
                                continue
                        else:
                            logger.warning(f"Transaction value is not a Value object: {type(txn_value)}")
                else:
                    logger.warning(f"Transaction missing value attribute or empty value list")

            except Exception as e:
                logger.error(f"Error creating Value/ProofUnit for transaction: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                continue

        logger.info(f"✅ 为账户 {account_addr} 创建了 {len(genesis_values)} 个Values和 {len(genesis_proof_units)} 个ProofUnits")
        return genesis_values, genesis_proof_units, block_index

    def _create_unified_genesis_transactions(self, accounts: List["Account"], sender_address: str) -> MultiTransactions:
        """
        Create ONE unified MultiTransactions for all genesis transactions

        This method creates a single MultiTransactions containing all the
        individual value distribution transactions for all accounts, since
        all transactions have the same sender (genesis account).

        Args:
            accounts: List of Account objects to receive initial values
            sender_address: Address of the genesis account (sender)

        Returns:
            MultiTransactions: Single unified genesis MultiTransactions containing all accounts' transactions
        """
        try:
            # Generate genesis key pair for signing
            genesis_private_key, genesis_public_key = secure_signature_handler.signer.generate_key_pair()

            # Create all individual transactions for all accounts
            all_transactions = []
            current_value_index = 0x1000  # Starting value index for genesis block

            logger.info(f"创建统一创世交易，包含 {len(accounts)} 个账户")

            for account in accounts:
                # Create individual transactions for each denomination value for this account
                for value_amount, count in self.denomination_config:
                    for _ in range(count):
                        # Calculate unique index for this value
                        begin_index = f"0x{current_value_index:04x}"

                        # Create a Value object for this denomination
                        genesis_value = Value(
                            beginIndex=begin_index,
                            valueNum=value_amount,
                            state=ValueState.UNSPENT
                        )

                        # Create a single transaction for this value
                        time_str = self.genesis_timestamp if isinstance(self.genesis_timestamp, str) else self.genesis_timestamp.isoformat()
                        transaction = Transaction(
                            sender=sender_address,
                            recipient=account.address,
                            nonce=len(all_transactions),  # Use transaction count as nonce
                            signature=None,  # Will be signed below
                            value=[genesis_value],
                            time=time_str
                        )

                        # Sign the transaction using genesis private key
                        transaction.sig_txn(genesis_private_key)

                        all_transactions.append(transaction)
                        current_value_index += value_amount

            if not all_transactions:
                logger.error("没有创建任何创世交易")
                raise ValueError("没有创建任何创世交易")

            # Create ONE unified MultiTransactions object containing ALL genesis transactions
            unified_multi_txn = MultiTransactions(
                sender=sender_address,
                multi_txns=all_transactions
            )

            # Sign the unified multi-transaction
            unified_multi_txn.sig_acc_txn(genesis_private_key)

            # Calculate and set the digest for the multi-transaction
            unified_multi_txn.set_digest()

            logger.info(f"✅ 创建统一创世MultiTransactions，包含 {len(all_transactions)} 个交易")
            return unified_multi_txn

        except Exception as e:
            logger.error(f"创建统一创世交易时出错: {e}")
            raise

    def _build_single_leaf_merkle_tree(self, submit_tx_info: SubmitTxInfo) -> MerkleTree:
        """
        Build a single-leaf Merkle tree for the SubmitTxInfo

        For unified genesis block, the merkle tree has exactly one leaf node,
        where the leaf hash equals the root hash for simplified verification.

        Args:
            submit_tx_info: SubmitTxInfo for the unified genesis transactions

        Returns:
            MerkleTree: Merkle tree with single node (the SubmitTxInfo hash)
        """
        try:
            logger.info("="*50)
            logger.info("开始构建单叶子节点创世默克尔树")

            # Get the hash of the single SubmitTxInfo
            submit_tx_hash = submit_tx_info.multi_transactions_hash

            logger.info(f"  - SubmitTxInfo哈希: {submit_tx_hash}")
            logger.info(f"  - submitter_address: {submit_tx_info.submitter_address}")

            # Create a merkle tree with just this single hash as both leaf and root
            logger.info("构建单节点MerkleTree...")
            merkle_tree = MerkleTree([submit_tx_hash])

            logger.info("="*50)
            logger.info("单节点MerkleTree构建完成!")
            logger.info(f"  - 默克尔树包含 1 个叶子节点")
            logger.info(f"  - 默克尔树根 (Merkle Root): {merkle_tree.get_root_hash()}")

            # 验证单节点树的一致性
            if merkle_tree.get_root_hash() != submit_tx_hash:
                logger.error("❌ 单节点Merkle树根与叶子哈希不匹配！")
                raise ValueError("单节点Merkle树构建失败：根哈希与叶子哈希不一致")

            logger.info("✅ 单节点Merkle树验证通过")
            logger.info("="*50)

            return merkle_tree

        except Exception as e:
            logger.error(f"构建单节点创世默克尔树时出错: {e}")
            raise

    def create_merkle_proof_for_submit_tx_info(self,
                                               submit_tx_info: SubmitTxInfo,
                                               merkle_tree: MerkleTree) -> MerkleTreeProof:
        """
        Create Merkle proof for the SubmitTxInfo in single-leaf genesis tree

        Args:
            submit_tx_info: The SubmitTxInfo object to create proof for
            merkle_tree: The single-leaf Merkle tree

        Returns:
            MerkleTreeProof: Merkle proof for the SubmitTxInfo
        """
        try:
            submit_tx_hash = submit_tx_info.multi_transactions_hash
            merkle_root = merkle_tree.get_root_hash()

            # For single-leaf tree, the proof should be just [root_hash]
            # In a single-leaf tree, leaf == root, so MerkleProof.check_prf expects mt_prf_list[0] to be the root
            # The check_prf method for single-element case: current_hash == mt_prf_list[0] == true_root
            proof_path = [merkle_root]  # Single element where leaf == root

            merkle_proof = MerkleTreeProof(proof_path)
            logger.debug(f"Created single-leaf merkle proof for {submit_tx_hash} (root == leaf)")

            return merkle_proof

        except Exception as e:
            logger.error(f"创建单叶子节点默克尔证明失败: {e}")
            raise

    def create_block_index(self, recipient_address: str) -> BlockIndexList:
        """
        Create BlockIndexList for genesis block

        Args:
            recipient_address: Address of the value recipient

        Returns:
            BlockIndexList: Block index information for genesis block
        """
        return BlockIndexList(
            index_lst=[GENESIS_BLOCK_INDEX],  # Genesis block index is 0
            owner=(GENESIS_BLOCK_INDEX, recipient_address)
        )

    def validate_genesis_block(self, genesis_block: Block) -> Tuple[bool, str]:
        """
        Validate a genesis block structure

        Args:
            genesis_block: Genesis block to validate

        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        try:
            # Check basic genesis block properties
            if genesis_block.index != GENESIS_BLOCK_INDEX:
                return False, f"Genesis block index should be {GENESIS_BLOCK_INDEX}, got {genesis_block.index}"

            if genesis_block.pre_hash != "0":
                return False, f"Genesis block previous hash should be '0', got {genesis_block.pre_hash}"

            if not genesis_block.m_tree_root:
                return False, "Genesis block missing merkle root"

            if not genesis_block.bloom:
                return False, "Genesis block missing bloom filter"

            return True, "Genesis block validation successful"

        except Exception as e:
            return False, f"Error validating genesis block: {str(e)}"


# ==================== PUBLIC API FUNCTIONS ====================

# Global creator instance for convenience
_global_creator = None


def get_genesis_creator(denomination_config: Optional[List[Tuple[int, int]]] = None) -> GenesisBlockCreator:
    """
    Get or create the global genesis creator instance

    Args:
        denomination_config: Optional custom denomination configuration

    Returns:
        GenesisBlockCreator: The genesis creator instance
    """
    global _global_creator
    if _global_creator is None or denomination_config is not None:
        _global_creator = GenesisBlockCreator(denomination_config)
    return _global_creator


def create_genesis_block(accounts: List["Account"],
                        denomination_config: Optional[List[Tuple[int, int]]] = None,
                        custom_miner: Optional[str] = None) -> Tuple[Block, SubmitTxInfo, MultiTransactions, MerkleTree]:
    """
    Create a unified genesis block with single MultiTransactions and single SubmitTxInfo

    Args:
        accounts: List of Account objects to receive initial values
        denomination_config: Custom denomination configuration
        custom_miner: Custom miner address

    Returns:
        Tuple[Block, SubmitTxInfo, MultiTransactions, MerkleTree]:
        - The created genesis block
        - Single SubmitTxInfo containing all transactions
        - Unified MultiTransactions containing all accounts' transactions
        - Merkle tree with single leaf node
    """
    logger.info("🚀 使用统一创世块创建API 🚀")

    creator = get_genesis_creator(denomination_config)
    return creator.create_unified_genesis_block(accounts, custom_miner)


def create_genesis_vpb_for_account(account_addr: str,
                                 genesis_block: Block,
                                 unified_submit_tx_info: SubmitTxInfo,
                                 unified_multi_txn: MultiTransactions,
                                 merkle_tree: MerkleTree,
                                 denomination_config: Optional[List[Tuple[int, int]]] = None) -> Tuple[List["Value"], List["ProofUnit"], BlockIndexList]:
    """
    Create complete VPB data for a single account from unified genesis block

    Args:
        account_addr: Account address string
        genesis_block: Genesis block containing the transaction
        unified_submit_tx_info: Unified SubmitTxInfo for ALL genesis transactions
        unified_multi_txn: Unified MultiTransactions containing ALL accounts' transactions
        merkle_tree: Merkle tree of the single genesis SubmitTxInfo
        denomination_config: Optional denomination configuration (for validation only)

    Returns:
        Tuple[List[Value], List[ProofUnit], BlockIndexList]:
        - List of Value objects created from the account's transactions
        - List of ProofUnit objects containing the proofs for each value
        - BlockIndexList containing the block index information
    """
    creator = get_genesis_creator(denomination_config)
    return creator.create_genesis_vpb_for_account(
        account_addr, genesis_block, unified_submit_tx_info, unified_multi_txn, merkle_tree
    )


def validate_genesis_block(genesis_block: Block) -> Tuple[bool, str]:
    """
    Validate a genesis block structure

    Args:
        genesis_block: Genesis block to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    creator = get_genesis_creator()
    return creator.validate_genesis_block(genesis_block)


# ==================== CLEANUP AND BACKWARDS COMPATIBILITY ====================

# Remove old interfaces that are no longer needed
# The old multi-SubmitTxInfo approach has been completely replaced by the unified approach

logger.info("EZChain Genesis Module loaded - Unified Genesis Architecture")
logger.info("Features: Single MultiTransactions, Single SubmitTxInfo, Single-Leaf Merkle Tree")