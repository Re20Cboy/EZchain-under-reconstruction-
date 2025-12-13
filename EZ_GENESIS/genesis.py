"""
EZChain Genesis Block Generator

This module implements the creation of genesis blocks for the EZChain blockchain system.
The genesis block serves as the starting point of the blockchain and is responsible for
initial value distribution and establishing the initial global state.

Core Responsibilities:
- Define Value Space: Establish discrete set of initial Values for the entire network
- Build Global State Anchor: Generate initial Merkle Root and Bloom Filter
- System Cold Start: Provide initial "evidence (P+B)" for subsequent VPB verification

Key Features:
- Compatible with existing VPB verification system
- Follows EZChain transaction format standards
- Integrates with Account and MultiTransactions architecture
- Generates proper Merkle proofs and block indices
"""

import datetime
import hashlib
import json
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

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

# VPB imports for create_genesis_vpb_for_account function
# These are imported here to support proper mocking in tests
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

    This class is responsible for creating genesis blocks that initialize
    the EZChain blockchain with distributed initial values among accounts.
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

    def create_genesis_block(self,
                           accounts: List["Account"],
                           custom_miner: Optional[str] = None) -> Tuple[Block, List[SubmitTxInfo]]:
        """
        Create genesis block with initial value distribution

        Args:
            accounts: List of Account objects to receive initial values
            custom_miner: Custom miner address (default: GENESIS_MINER)

        Returns:
            Tuple[Block, List[SubmitTxInfo]]: The created genesis block and list of SubmitTxInfo

        Raises:
            ValueError: If no accounts provided or invalid parameters
        """
        logger.info("🌟 ===== 开始创建创世块 ===== 🌟")

        if not accounts:
            raise ValueError("At least one account must be provided for genesis block")

        # Always use genesis account as sender - no backward compatibility for custom_sender
        sender_address = self.genesis_manager.get_genesis_address()
        private_key_pem = self.genesis_manager.get_private_key_pem()
        public_key_pem = self.genesis_manager.get_public_key_pem()

        miner_address = custom_miner or GENESIS_MINER

        logger.info(f"为 {len(accounts)} 个账户创建创世块")
        logger.info(f"发送者: {sender_address}, 矿工: {miner_address}")
        logger.info(f"账户列表: {[acc.address for acc in accounts]}")

        # Step 1: Create genesis transactions for all accounts
        logger.info("\n=== 步骤1: 为所有账户创建创世交易 ===")
        genesis_multi_txns = self._create_genesis_transactions(accounts, sender_address)
        logger.info(f"创建了 {len(genesis_multi_txns)} 个MultiTransactions对象")

        # Step 2: Create SubmitTxInfo for each MultiTransactions
        logger.info("\n=== 步骤2: 为每个MultiTransactions创建SubmitTxInfo ===")
        genesis_submit_tx_infos = []
        for i, multi_txn in enumerate(genesis_multi_txns):
            submit_tx_info = SubmitTxInfo(multi_txn, private_key_pem, public_key_pem)
            genesis_submit_tx_infos.append(submit_tx_info)
            logger.info(f"  SubmitTxInfo #{i+1} 已创建，哈希: {submit_tx_info.multi_transactions_hash}")

        # Step 3: Build Merkle tree from all SubmitTxInfo (instead of MultiTransactions)
        logger.info("\n=== 步骤3: 从所有SubmitTxInfo构建默克尔树 ===")
        merkle_tree, merkle_proofs = self._build_genesis_merkle_tree_from_submit_tx_infos(genesis_submit_tx_infos)

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

        # Step 5: Add transaction submitter addresses to bloom filter
        logger.info("\n=== 步骤5: 添加提交者地址到布隆过滤器 ===")
        for submit_tx_info in genesis_submit_tx_infos:
            genesis_block.add_item_to_bloom(submit_tx_info.submitter_address)
            logger.info(f"  已添加提交者地址到布隆过滤器: {submit_tx_info.submitter_address}")

        logger.info("\n🎉 ===== 创世块创建完成 ===== 🎉")
        logger.info(f"  - 创世块索引: {genesis_block.index}")
        logger.info(f"  - 矿工地址: {genesis_block.miner}")
        logger.info(f"  - 前一个区块哈希: {genesis_block.pre_hash}")
        logger.info(f"  - 随机数 (nonce): {genesis_block.nonce}")
        logger.info(f"  - 时间戳: {genesis_block.time}")
        logger.info(f"  - 默克尔树根 (Merkle Root): {genesis_block.m_tree_root}")
        logger.info(f"  - 包含 SubmitTxInfo 数量: {len(genesis_submit_tx_infos)}")
        logger.info(f"  - 布隆过滤器大小: {len(genesis_block.bloom) if genesis_block.bloom else 'N/A'}")

        # Store genesis_submit_tx_infos for use in create_genesis_vpb_for_account
        self._genesis_submit_tx_infos = genesis_submit_tx_infos

        return genesis_block, genesis_submit_tx_infos

    def create_merkle_proof(self,
                          multi_txn: MultiTransactions,
                          merkle_tree: MerkleTree) -> MerkleTreeProof:
        """
        Create Merkle proof for a specific transaction in genesis block

        Args:
            multi_txn: The MultiTransactions object to create proof for
            merkle_tree: The Merkle tree containing all genesis transactions

        Returns:
            MerkleTreeProof: Merkle proof for the transaction
        """
        # Find leaf index for this multi_txn
        leaf_index = self._find_leaf_index(multi_txn, merkle_tree)

        if leaf_index is None:
            logger.error(f"MultiTransactions not found in merkle tree: {multi_txn.digest}")
            raise ValueError(f"MultiTransactions not found in merkle tree: {multi_txn.digest}")

        # Generate proper merkle proof using the tree structure
        # Since we fixed the MerkleTree construction, we should always have valid prf_list
        if (hasattr(merkle_tree, 'prf_list') and
            merkle_tree.prf_list is not None and
            leaf_index is not None and
            leaf_index < len(merkle_tree.prf_list)):
            proof_path = merkle_tree.prf_list[leaf_index]
            if proof_path and len(proof_path) > 0:
                # Create MerkleTreeProof with the proper path from the tree
                merkle_proof = MerkleTreeProof(proof_path)
                logger.debug(f"Created merkle proof for {multi_txn.digest} with {len(proof_path)} elements")
                return merkle_proof
            else:
                logger.error(f"Empty proof path generated for leaf index {leaf_index}")

        # If we get here, something went wrong with the merkle tree construction
        logger.error(f"Failed to generate merkle proof: prf_list unavailable or invalid for leaf index {leaf_index}")
        raise ValueError(f"Failed to generate valid merkle proof for MultiTransactions {multi_txn.digest}")

    def create_merkle_proof_for_submit_tx_info(self,
                                               submit_tx_info: SubmitTxInfo,
                                               merkle_tree: MerkleTree) -> MerkleTreeProof:
        """
        Create Merkle proof for a specific SubmitTxInfo in genesis block

        Args:
            submit_tx_info: The SubmitTxInfo object to create proof for
            merkle_tree: The Merkle tree containing all genesis SubmitTxInfo

        Returns:
            MerkleTreeProof: Merkle proof for the SubmitTxInfo
        """
        # Find leaf index for this SubmitTxInfo
        leaf_index = self._find_leaf_index_for_submit_tx_info(submit_tx_info, merkle_tree)

        if leaf_index is None:
            logger.error(f"SubmitTxInfo not found in merkle tree: {submit_tx_info.multi_transactions_hash}")
            raise ValueError(f"SubmitTxInfo not found in merkle tree: {submit_tx_info.multi_transactions_hash}")

        # Generate proper merkle proof using the tree structure
        # Since we fixed the MerkleTree construction, we should always have valid prf_list
        if (hasattr(merkle_tree, 'prf_list') and
            merkle_tree.prf_list is not None and
            leaf_index is not None and
            leaf_index < len(merkle_tree.prf_list)):
            proof_path = merkle_tree.prf_list[leaf_index]
            if proof_path and len(proof_path) > 0:
                # Create MerkleTreeProof with the proper path from the tree
                merkle_proof = MerkleTreeProof(proof_path)
                logger.debug(f"Created merkle proof for {submit_tx_info.multi_transactions_hash} with {len(proof_path)} elements")
                return merkle_proof
            else:
                logger.error(f"Empty proof path generated for leaf index {leaf_index}")

        # If we get here, something went wrong with the merkle tree construction
        logger.error(f"Failed to generate merkle proof: prf_list unavailable or invalid for leaf index {leaf_index}")
        raise ValueError(f"Failed to generate valid merkle proof for SubmitTxInfo {submit_tx_info.multi_transactions_hash}")

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

    def create_genesis_vpb(self,
                          account: "Account",
                          genesis_multi_txn: MultiTransactions,
                          merkle_proof: MerkleTreeProof,
                          block_index: BlockIndexList) -> ProofUnit:
        """
        Create VPB (Value-Proofs-BlockIndex) data for an account in genesis block

        Args:
            account: Account object to receive the genesis VPB
            genesis_multi_txn: MultiTransactions for the account
            merkle_proof: Merkle proof for the transaction
            block_index: Block index information

        Returns:
            ProofUnit: VPB proof unit for the account
        """
        # Create ProofUnit
        proof_unit = ProofUnit(
            owner=account.address,
            owner_multi_txns=genesis_multi_txn,
            owner_mt_proof=merkle_proof
        )

        # Reduced verbosity for genesis VPB creation
        # logger.info(f"Created genesis VPB for account {account.address}")
        # logger.info(f"Proof unit ID: {proof_unit.unit_id}")

        return proof_unit

    def _create_genesis_transactions(self,
                                    accounts: List["Account"],
                                    sender_address: str) -> List[MultiTransactions]:
        """
        Create genesis transactions for all accounts

        Args:
            accounts: List of Account objects to receive values
            sender_address: Genesis sender address

        Returns:
            List[MultiTransactions]: List of genesis multi-transactions
        """
        genesis_multi_txns = []

        # Generate genesis key pair for signing
        try:
            genesis_private_key, genesis_public_key = secure_signature_handler.signer.generate_key_pair()
        except Exception as e:
            logger.error(f"Failed to generate genesis key pair: {e}")
            # Fallback: create dummy keys for testing
            genesis_private_key = b"dummy_private_key"
            genesis_public_key = b"dummy_public_key"

        for account in accounts:
            try:
                # Create MultiTransactions for this account
                multi_txn = self._create_account_genesis_transaction(
                    account=account,
                    sender_address=sender_address,
                    genesis_private_key=genesis_private_key,
                    genesis_public_key=genesis_public_key
                )

                if multi_txn:
                    genesis_multi_txns.append(multi_txn)
                    # Removed redundant logging - detailed creation log is already provided by outer method
                else:
                    logger.error(f"Failed to create genesis transaction for account {account.address}")

            except Exception as e:
                logger.error(f"Error creating genesis transaction for account {account.address}: {e}")
                continue

        return genesis_multi_txns

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

            logger.info(f"Creating unified genesis transactions for {len(accounts)} accounts")

            for account in accounts:
                # Create individual transactions for each denomination value for this account
                for value_amount, count in self.denomination_config:
                    for _ in range(count):
                        # Calculate unique index for this value
                        begin_index = f"0x{current_value_index:04x}"

                        # Create a Value object for this denomination
                        from EZ_VPB.values.Value import Value, ValueState
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
                logger.error("No transactions created for unified genesis block")
                raise ValueError("No transactions created for unified genesis block")

            # Create ONE unified MultiTransactions object containing ALL genesis transactions
            unified_multi_txn = MultiTransactions(
                sender=sender_address,
                multi_txns=all_transactions
            )

            # Sign the unified multi-transaction
            unified_multi_txn.sig_acc_txn(genesis_private_key)

            logger.info(f"Created unified genesis MultiTransactions with {len(all_transactions)} total transactions for {len(accounts)} accounts")
            return unified_multi_txn

        except Exception as e:
            logger.error(f"Error creating unified genesis transactions: {e}")
            raise

    def _build_genesis_merkle_tree_from_single_submit_tx_info(self, submit_tx_info: SubmitTxInfo) -> MerkleTree:
        """
        Build a merkle tree from a single SubmitTxInfo (special case for genesis block)

        For genesis block with single SubmitTxInfo, the merkle tree is just the hash itself
        to maintain compatibility with the merkle proof system.

        Args:
            submit_tx_info: Single SubmitTxInfo for genesis block

        Returns:
            MerkleTree: Merkle tree with single node (the SubmitTxInfo hash)
        """
        try:
            from EZ_Units.MerkleTree import MerkleTree

            logger.info("="*50)
            logger.info("开始构建单节点创世默克尔树")

            # Get the hash of the single SubmitTxInfo
            submit_tx_hash = submit_tx_info.multi_transactions_hash

            logger.info(f"  - SubmitTxInfo哈希: {submit_tx_hash}")
            logger.info(f"  - submitter_address: {submit_tx_info.submitter_address}")

            # 记录multi_transactions_hash的详细信息
            multi_transactions_hash = submit_tx_info.multi_transactions_hash
            logger.info(f"  - multi_transactions_hash: {multi_transactions_hash}")

            # 注意：SubmitTxInfo只包含哈希，不包含完整的multi_transactions对象
            # 所以无法获取详细的总价值和接收账户信息

            # Create a merkle tree with just this single hash as both leaf and root
            logger.info("构建单节点MerkleTree...")
            merkle_tree = MerkleTree([submit_tx_hash])

            logger.info("="*50)
            logger.info("单节点MerkleTree构建完成!")
            logger.info(f"  - 默克尔树包含 1 个叶子节点")
            logger.info(f"  - 默克尔树根 (Merkle Root): {merkle_tree.get_root_hash()}")

            # 记录叶子节点信息
            if hasattr(merkle_tree, 'leaves') and merkle_tree.leaves:
                logger.info(f"  - 叶子节点内容: {merkle_tree.leaves[0] if hasattr(merkle_tree.leaves[0], 'content') or hasattr(merkle_tree.leaves[0], 'value') else str(merkle_tree.leaves[0])}")

            # 记录prf_list信息（如果存在）
            if hasattr(merkle_tree, 'prf_list') and merkle_tree.prf_list:
                logger.info(f"  - 证明路径列表 (prf_list): {len(merkle_tree.prf_list)} 个条目")
                if merkle_tree.prf_list[0]:
                    logger.info(f"    [0] 证明路径: {merkle_tree.prf_list[0]}")
            else:
                logger.warning("  - 证明路径列表 (prf_list) 为空或不存在")
            logger.info("="*50)

            return merkle_tree

        except Exception as e:
            logger.error(f"Error creating single-node genesis merkle tree: {e}")
            raise

    def _create_account_genesis_transaction(self,
                                           account: "Account",
                                           sender_address: str,
                                           genesis_private_key: bytes,
                                           genesis_public_key: bytes) -> Optional[MultiTransactions]:
        """
        Create genesis transaction for a single account using special value creation logic

        This method bypasses the regular balance checking system and creates values
        from scratch, which is appropriate for genesis transactions.

        Args:
            account: Account object to receive values
            sender_address: Genesis sender address
            genesis_private_key: Private key for signing (in bytes)
            genesis_public_key: Public key for verification (in bytes)

        Returns:
            MultiTransactions: Genesis multi-transaction for the account
        """
        try:
            logger.info(f"Creating genesis transactions for account {account.address}")

            # Create individual transactions for each denomination value
            transactions = []
            created_values = []
            current_value_index = 0x1000  # Starting value index for this account

            # Create individual transactions for each denomination config entry
            for value_amount, count in self.denomination_config:
                for _ in range(count):
                    # Calculate unique index for this value
                    begin_index = f"0x{current_value_index:04x}"

                    # Removed verbose logging for each genesis value creation

                    # Create a Value object for this denomination
                    genesis_value = Value(
                        beginIndex=begin_index,
                        valueNum=value_amount,
                        state=ValueState.UNSPENT
                    )
                    # Created genesis value
                    created_values.append(genesis_value)

                    # Create a single transaction for this value
                    # Convert datetime to string for JSON serialization compatibility
                    time_str = self.genesis_timestamp if isinstance(self.genesis_timestamp, str) else self.genesis_timestamp.isoformat()
                    transaction = Transaction(
                        sender=sender_address,
                        recipient=account.address,
                        nonce=len(transactions),  # Use transaction count as nonce
                        signature=None,  # Will be signed below
                        value=[genesis_value],
                        time=time_str
                    )

                    # Sign the transaction using genesis private key
                    transaction.sig_txn(genesis_private_key)

                    transactions.append(transaction)
                    current_value_index += value_amount

            if not transactions:
                logger.error(f"No transactions created for account {account.address}")
                return None

            # Create MultiTransactions object containing all genesis transactions
            multi_txn = MultiTransactions(
                sender=sender_address,
                multi_txns=transactions
            )

            # Set the timestamp for the batch (ensure string format)
            multi_txn.time = time_str

            # Sign the MultiTransactions using genesis private key
            multi_txn.sig_acc_txn(genesis_private_key)

            # Calculate and set the digest for the multi-transaction
            multi_txn.set_digest()

            logger.info(f"Successfully created {len(transactions)} genesis transactions for account {account.address}")
            logger.info(f"Total value created: {self.total_initial_value}")

            # Genesis values created successfully

            # Store created values for later use in VPB creation
            if not hasattr(self, '_genesis_values_by_account'):
                self._genesis_values_by_account = {}
            self._genesis_values_by_account[account.address] = created_values

            return multi_txn

        except Exception as e:
            logger.error(f"Error creating genesis transaction for account {account.address}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _build_genesis_merkle_tree(self,
                                  genesis_multi_txns: List[MultiTransactions]) -> Tuple[MerkleTree, Dict]:
        """
        Build Merkle tree for genesis transactions

        Args:
            genesis_multi_txns: List of genesis multi-transactions

        Returns:
            Tuple[MerkleTree, Dict]: Merkle tree and proof mapping
        """
        # Create list of transaction digests for merkle tree
        txn_digests = [multi_txn.digest for multi_txn in genesis_multi_txns]

        # Handle empty transaction list case
        if not txn_digests:
            logger.warning("No genesis transactions created, using empty merkle tree")
            # Create a merkle tree with a single placeholder digest
            txn_digests = ["genesis_empty_placeholder"]

        # Build merkle tree
        merkle_tree = MerkleTree(txn_digests)

        logger.info(f"Built genesis merkle tree with {len(txn_digests)} transactions")
        logger.info(f"Merkle root: {merkle_tree.get_root_hash()}")

        return merkle_tree, {}

    def _build_genesis_merkle_tree_from_submit_tx_infos(self,
                                                       genesis_submit_tx_infos: List[SubmitTxInfo]) -> Tuple[MerkleTree, Dict]:
        """
        Build Merkle tree from genesis SubmitTxInfo transactions


        Args:
            genesis_submit_tx_infos: List of genesis SubmitTxInfo objects

        Returns:
            Tuple[MerkleTree, Dict]: Merkle tree and proof mapping
        """
        logger.info("="*50)
        logger.info("开始构建创世块的默克尔树")
        logger.info(f"总共收到 {len(genesis_submit_tx_infos)} 个SubmitTxInfo对象")

        # Create list of SubmitTxInfo hashes for merkle tree
        submit_tx_hashes = []

        # 详细记录每个SubmitTxInfo的信息
        for i, submit_tx_info in enumerate(genesis_submit_tx_infos):
            submit_tx_hash = submit_tx_info.multi_transactions_hash
            submit_tx_hashes.append(submit_tx_hash)

            logger.info(f"  SubmitTxInfo #{i+1}:")
            logger.info(f"    - submit_tx_hash: {submit_tx_hash}")
            logger.info(f"    - submitter_address: {submit_tx_info.submitter_address}")
            logger.info(f"    - multi_transactions_hash: {submit_tx_info.multi_transactions_hash}")

            # 注意：SubmitTxInfo只包含哈希，无法直接获取multi_transactions的详细信息

        logger.info("-"*30)
        logger.info(f"所有submit_tx_hash汇总:")
        for i, hash_val in enumerate(submit_tx_hashes):
            logger.info(f"  [{i}] {hash_val}")
        logger.info("-"*30)

        # Handle empty transaction list case
        if not submit_tx_hashes:
            logger.warning("没有创世SubmitTxInfo被创建，使用空的默克尔树")
            # Create a merkle tree with a single placeholder digest
            submit_tx_hashes = ["genesis_empty_placeholder"]
            logger.warning(f"使用占位符: {submit_tx_hashes[0]}")

        # Build merkle tree
        logger.info("开始构建MerkleTree对象...")
        merkle_tree = MerkleTree(submit_tx_hashes)

        logger.info("="*50)
        logger.info("MerkleTree构建完成!")
        logger.info(f"  - 默克尔树包含 {len(submit_tx_hashes)} 个叶子节点")
        logger.info(f"  - 默克尔树根 (Merkle Root): {merkle_tree.get_root_hash()}")

        # 如果有prf_list，记录其信息
        if hasattr(merkle_tree, 'prf_list') and merkle_tree.prf_list:
            logger.info(f"  - 证明路径列表 (prf_list) 包含 {len(merkle_tree.prf_list)} 个条目")
            for i, proof_path in enumerate(merkle_tree.prf_list):
                if proof_path:
                    logger.info(f"    [{i}] 证明路径长度: {len(proof_path)}")
                else:
                    logger.info(f"    [{i}] 证明路径: 空")
        else:
            logger.warning("  - 证明路径列表 (prf_list) 为空或不存在")

        logger.info(f"  - 叶子节点数量: {len(merkle_tree.leaves) if hasattr(merkle_tree, 'leaves') else 'N/A'}")
        logger.info("="*50)

        return merkle_tree, {}

    def _find_leaf_index(self, multi_txn: MultiTransactions, merkle_tree: MerkleTree) -> Optional[int]:
        """
        Find leaf index of a multi-transaction in merkle tree

        Args:
            multi_txn: MultiTransactions to find
            merkle_tree: Merkle tree to search in

        Returns:
            Optional[int]: Leaf index if found, None otherwise
        """
        try:
            # Search through leaves to find matching digest
            for i, leaf in enumerate(merkle_tree.leaves):
                # Check if leaf has content attribute and it matches
                if hasattr(leaf, 'content') and leaf.content == multi_txn.digest:
                    return i
                # Handle case where leaf itself is a string (for testing)
                elif hasattr(leaf, 'value') and leaf.value == multi_txn.digest:
                    return i
        except Exception as e:
            logger.error(f"Error finding leaf index: {e}")

        return None

    def _find_leaf_index_for_submit_tx_info(self, submit_tx_info: SubmitTxInfo, merkle_tree: MerkleTree) -> Optional[int]:
        """
        Find leaf index of a SubmitTxInfo in merkle tree

        Args:
            submit_tx_info: SubmitTxInfo to find
            merkle_tree: Merkle tree to search in

        Returns:
            Optional[int]: Leaf index if found, None otherwise
        """
        try:
            # Search through leaves to find matching hash
            for i, leaf in enumerate(merkle_tree.leaves):
                # Check if leaf has content attribute and it matches
                if hasattr(leaf, 'content') and leaf.content == submit_tx_info.multi_transactions_hash:
                    return i
                # Handle case where leaf itself is a string (for testing)
                elif hasattr(leaf, 'value') and leaf.value == submit_tx_info.multi_transactions_hash:
                    return i
                # Handle case where leaf is directly the hash string
                elif isinstance(leaf, str) and leaf == submit_tx_info.multi_transactions_hash:
                    return i
        except Exception as e:
            logger.error(f"Error finding leaf index for SubmitTxInfo: {e}")

        return None

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


# Convenience functions for external use
def create_genesis_block(accounts: List["Account"],
                        denomination_config: Optional[List[Tuple[int, int]]] = None,
                        custom_miner: Optional[str] = None) -> Tuple[Block, List[SubmitTxInfo], List[MultiTransactions], MerkleTree]:
    """
    Convenience function to create a genesis block

    Args:
        accounts: List of Account objects to receive initial values
        denomination_config: Custom denomination configuration
        custom_miner: Custom miner address

    Returns:
        Tuple[Block, List[SubmitTxInfo], List[MultiTransactions], MerkleTree]:
        The created genesis block, single SubmitTxInfo list, single MultiTransactions list, and MerkleTree
    """
    logger.info("🚀 使用便捷函数创建创世块 🚀")

    creator = GenesisBlockCreator(denomination_config)

    # Create ONE unified MultiTransactions for all genesis transactions
    from EZ_GENESIS.genesis_account import get_genesis_manager
    genesis_manager = get_genesis_manager()
    logger.info(f"为 {len(accounts)} 个账户创建统一的MultiTransactions")

    unified_genesis_multi_txn = creator._create_unified_genesis_transactions(accounts, genesis_manager.get_genesis_address())
    logger.info(f"统一MultiTransactions包含 {len(unified_genesis_multi_txn.multi_txns)} 个交易")

    # Generate genesis key pair for signing
    genesis_private_key_pem, genesis_public_key_pem = secure_signature_handler.signer.generate_key_pair()

    # Create ONE SubmitTxInfo for the unified MultiTransactions
    genesis_submit_tx_info = SubmitTxInfo(unified_genesis_multi_txn, genesis_private_key_pem, genesis_public_key_pem)
    genesis_submit_tx_infos = [genesis_submit_tx_info]  # Single element list

    logger.info(f"统一的SubmitTxInfo哈希: {genesis_submit_tx_info.multi_transactions_hash}")

    # Build Merkle tree from single SubmitTxInfo (special case for genesis)
    merkle_tree = creator._build_genesis_merkle_tree_from_single_submit_tx_info(genesis_submit_tx_info)

    # Create genesis block
    miner_address = custom_miner or GENESIS_MINER
    merkle_root = merkle_tree.get_root_hash()

    logger.info(f"\n🌟 便捷函数创建创世块总结:")
    logger.info(f"  - 账户数量: {len(accounts)}")
    logger.info(f"  - 总交易数: {len(unified_genesis_multi_txn.multi_txns)}")
    logger.info(f"  - SubmitTxInfo 数量: 1 (统一)")
    logger.info(f"  - 矿工地址: {miner_address}")
    logger.info(f"  - 最终默克尔树根: {merkle_root}")

    genesis_block = Block(
        index=GENESIS_BLOCK_INDEX,
        m_tree_root=merkle_root,
        miner=miner_address,
        pre_hash="0",  # Genesis block has no previous hash
        nonce=0,  # No mining needed for genesis
        time=creator.genesis_timestamp
    )

    # Add transaction submitter address to bloom filter (only one - genesis sender)
    genesis_block.add_item_to_bloom(genesis_submit_tx_info.submitter_address)

    logger.info(f"\n✅ 便捷函数创世块创建完成! 默克尔树根: {genesis_block.m_tree_root}")

    # Return single MultiTransactions in list for compatibility
    return genesis_block, genesis_submit_tx_infos, [unified_genesis_multi_txn], merkle_tree


def create_genesis_vpb_for_account(account_addr: str,
                                 genesis_block: Block,
                                 unified_genesis_submit_tx_info: SubmitTxInfo,
                                 unified_genesis_multi_txn: MultiTransactions,
                                 merkle_tree: MerkleTree,
                                 denomination_config: Optional[List[Tuple[int, int]]] = None) -> Tuple[List["Value"], List["ProofUnit"], BlockIndexList]:
    """
    Create complete VPB data for a single account from genesis block using unified SubmitTxInfo and MultiTransactions
    Genesis miner creates VPB data for account initialization, compatible with VPBManager.initialize_from_genesis method

    Args:
        account_addr: Account address string
        genesis_block: Genesis block containing the transaction
        unified_genesis_submit_tx_info: Unified SubmitTxInfo for ALL genesis transactions (for merkle proof)
        unified_genesis_multi_txn: Unified MultiTransactions containing ALL accounts' transactions
        merkle_tree: Merkle tree of the single genesis SubmitTxInfo
        denomination_config: List of (amount, count) tuples for value distribution

    Returns:
        Tuple[List[Value], List[ProofUnit], BlockIndexList]:
        - List of Value objects created from the account's transactions
        - List of ProofUnit objects containing the proofs for each value
        - BlockIndexList containing the block index information

    Note:
        This function only creates VPB data. The account holder should
        receive this data and manually call their VPBManager.initialize_from_genesis()
        to process it in the distributed blockchain system.
    """
    creator = GenesisBlockCreator(denomination_config)

    # Create Merkle proof for the unified SubmitTxInfo (single genesis transaction)
    # This ensures consistency with normal VPB updates that use SubmitTxInfo hashes as merkle tree leaves
    merkle_proof = creator.create_merkle_proof_for_submit_tx_info(unified_genesis_submit_tx_info, merkle_tree)

    # Create block index for the account
    block_index = creator.create_block_index(account_addr)

    # Create Value objects and corresponding ProofUnits for each transaction
    genesis_values = []
    genesis_proof_units = []

    if not unified_genesis_multi_txn or not unified_genesis_multi_txn.multi_txns:
        logger.error(f"No transactions found for account {account_addr}")
        return [], [], block_index

    # Create Value and ProofUnit for transactions that belong to this account
    for txn in unified_genesis_multi_txn.multi_txns:
        try:
            # Extract Value information from transaction's value list
            if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                # Each transaction should contain one Value object for genesis
                for txn_value in txn.value:
                    if isinstance(txn_value, Value):
                        # Only process transactions that belong to this account (as recipient)
                        if hasattr(txn, 'recipient') and txn.recipient == account_addr:
                            # Extract genesis value from transaction
                            # Use the Value object directly from the transaction
                            genesis_values.append(txn_value)

                            # Create ProofUnit for this value using the UNIFIED MultiTransactions and the SAME merkle proof
                            # All genesis VPBs should reference the same unified MultiTransactions and SubmitTxInfo merkle proof
                            proof_unit = ProofUnit(
                                owner=account_addr,
                                owner_multi_txns=unified_genesis_multi_txn,  # Use the unified MultiTransactions
                                owner_mt_proof=merkle_proof  # Use the same merkle proof for all values
                            )
                            genesis_proof_units.append(proof_unit)

                            # Detailed value creation logging - commented out to reduce verbosity
                            # logger.info(f"Created Value {txn_value.begin_index}-{txn_value.end_index} (amount: {txn_value.value_num}) for account {account_addr}")
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

    # Reduced verbosity for summary - uncomment if detailed debugging needed
        # logger.info(f"Created {len(genesis_values)} Values and {len(genesis_proof_units)} ProofUnits for account {account_addr}")

    # Reduced final logging verbosity
        # logger.info(f"Genesis VPB data created for account {account_addr}. Ready for distribution.")

    return genesis_values, genesis_proof_units, block_index


def validate_genesis_block(genesis_block: Block) -> Tuple[bool, str]:
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


def create_genesis_vpb_for_account_from_submit_tx_info(account_addr: str,
                                                      genesis_block: Block,
                                                      genesis_submit_tx_info: SubmitTxInfo,
                                                      merkle_tree: MerkleTree,
                                                      denomination_config: Optional[List[Tuple[int, int]]] = None) -> Tuple[List["Value"], List["ProofUnit"], BlockIndexList]:
    """
    Create complete VPB data for a single account from genesis block using SubmitTxInfo
    New version that works with SubmitTxInfo instead of MultiTransactions

    Args:
        account_addr: Account address string
        genesis_block: Genesis block containing the transaction
        genesis_submit_tx_info: SubmitTxInfo for the account
        merkle_tree: Merkle tree of genesis SubmitTxInfo transactions
        denomination_config: List of (amount, count) tuples for value distribution

    Returns:
        Tuple[List[Value], List[ProofUnit], BlockIndexList]:
        - List of Value objects created from the account's transactions
        - List of ProofUnit objects containing the proofs for each value
        - BlockIndexList containing the block index information

    Note:
        This function only creates VPB data. The account holder should
        receive this data and manually call their VPBManager.initialize_from_genesis()
        to process it in the distributed blockchain system.
    """
    creator = GenesisBlockCreator(denomination_config)

    # Create Merkle proof for the account's SubmitTxInfo
    merkle_proof = creator.create_merkle_proof_for_submit_tx_info(genesis_submit_tx_info, merkle_tree)

    # Create block index for the account
    block_index = creator.create_block_index(account_addr)

    # Create Value objects and corresponding ProofUnits for each transaction
    genesis_values = []
    genesis_proof_units = []

    if not genesis_submit_tx_info.multi_transactions.multi_txns:
        logger.error(f"No transactions found for account {account_addr}")
        return [], [], block_index

    # Create Value and ProofUnit for each individual transaction
    for txn in genesis_submit_tx_info.multi_transactions.multi_txns:
        try:
            # Extract Value information from transaction's value list
            if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                # Each transaction should contain one Value object for genesis
                for txn_value in txn.value:
                    if isinstance(txn_value, Value):
                        # Extract genesis value from transaction
                        # Use the Value object directly from the transaction
                        genesis_values.append(txn_value)

                        # Create a single-transaction MultiTransactions for this value
                        single_multi_txn = MultiTransactions(
                            sender=genesis_submit_tx_info.multi_transactions.sender,
                            multi_txns=[txn]  # Only this specific transaction
                        )

                        # Create real ProofUnit for this specific value
                        proof_unit = ProofUnit(
                            owner=account_addr,
                            owner_multi_txns=single_multi_txn,
                            owner_mt_proof=merkle_proof
                        )
                        genesis_proof_units.append(proof_unit)
                    else:
                        logger.warning(f"Transaction value is not a Value object: {type(txn_value)}")
            else:
                logger.warning(f"Transaction missing value attribute or empty value list")

        except Exception as e:
            logger.error(f"Error creating Value/ProofUnit for transaction: {e}")
            import traceback
            traceback.print_exc()
            continue

    logger.info(f"Created {len(genesis_values)} values and {len(genesis_proof_units)} proof units for account {account_addr}")

    return genesis_values, genesis_proof_units, block_index