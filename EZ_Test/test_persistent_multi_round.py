#!/usr/bin/env python3
"""
EZchain 持久化多轮交易测试
支持永久存储，测试可以中断后继续运行
"""

import sys
import os
import json
import time
import shutil
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Main_Chain.Block import Block
from EZ_Tx_Pool.TXPool import TxPool
from EZ_Tx_Pool.PickTx import TransactionPicker, pick_transactions_from_pool_with_proofs
from EZ_Transaction.SubmitTxInfo import SubmitTxInfo
from EZ_Transaction.MultiTransactions import MultiTransactions
from EZ_Account.Account import Account
from EZ_VPB.values.Value import Value, ValueState
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_GENESIS.genesis import create_genesis_block, create_genesis_vpb_for_account
from EZ_Miner.miner import Miner

# 配置日志
import logging
logging.basicConfig(
    level=logging.CRITICAL,
    format='%(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 关闭详细日志
for logger_name in ['EZ_VPB_Validator', 'EZ_VPB_Validator.VPBSliceGenerator',
                   'EZ_VPB_Validator.DataStructureValidator', 'EZ_VPB_Validator.BloomFilterValidator',
                   'EZ_VPB_Validator.proof_validator', 'EpochExtractor', 'DataStructureValidator',
                   'VPBSliceGenerator', 'BloomFilterValidator', 'VPBValidator',
                   'EZ_Tool_Box', 'SecureSignature', 'MultiTransactions', 'SingleTransaction',
                   'TxPool', 'PickTx', 'AccountProofManager', 'AccountValueCollection']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

genesis_logger = logging.getLogger('EZ_GENESIS')
genesis_logger.setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class PersistentTestState:
    """持久化测试状态管理器"""

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.state_file = os.path.join(storage_dir, "persistent_test_state.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """加载测试状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载状态文件失败: {e}")
        return self._get_default_state()

    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            "current_round": 0,
            "target_rounds": 20,
            "initialized": False,
            "accounts": [],
            "last_update": None,
            "blockchain_data_dir": None,
            "pool_db_path": None,
            "account_storage_dir": None
        }

    def save_state(self):
        """保存测试状态"""
        self.state["last_update"] = datetime.now().isoformat()
        try:
            os.makedirs(self.storage_dir, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.info(f"状态已保存: 轮次 {self.state['current_round']}/{self.state['target_rounds']}")
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def get_current_round(self) -> int:
        return self.state.get("current_round", 0)

    def get_target_rounds(self) -> int:
        return self.state.get("target_rounds", 20)

    def is_initialized(self) -> bool:
        return self.state.get("initialized", False)

    def set_initialized(self, initialized: bool):
        self.state["initialized"] = initialized

    def increment_round(self):
        self.state["current_round"] += 1

    def set_storage_paths(self, blockchain_dir: str, pool_db: str, account_dir: str):
        self.state["blockchain_data_dir"] = blockchain_dir
        self.state["pool_db_path"] = pool_db
        self.state["account_storage_dir"] = account_dir

    def get_storage_paths(self) -> tuple:
        return (
            self.state.get("blockchain_data_dir"),
            self.state.get("pool_db_path"),
            self.state.get("account_storage_dir")
        )

    def set_accounts(self, accounts_data: List[Dict]):
        self.state["accounts"] = accounts_data

    def get_accounts(self) -> List[Dict]:
        return self.state.get("accounts", [])

    def reset(self):
        """重置测试状态"""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        self.state = self._get_default_state()
        logger.info("测试状态已重置")


class PersistentMultiRoundTester:
    """持久化多轮测试器"""

    def __init__(self, base_storage_dir: str = None, target_rounds: int = 20):
        # 默认存储目录为 EZ_Test/persistent_test_data
        if base_storage_dir is None:
            # 获取 EZ_Test 目录的绝对路径
            ez_test_dir = os.path.dirname(os.path.abspath(__file__))
            base_storage_dir = os.path.join(ez_test_dir, "persistent_test_data")

        self.base_storage_dir = base_storage_dir
        self.target_rounds = target_rounds

        # 创建状态管理器
        self.state_manager = PersistentTestState(self.base_storage_dir)

        # 核心组件
        self.blockchain: Optional[Blockchain] = None
        self.transaction_pool: Optional[TxPool] = None
        self.transaction_picker: Optional[TransactionPicker] = None
        self.accounts: List[Account] = []
        self.miner: Optional[Miner] = None
        self.miner_address = "persistent_test_miner"

        # 账户地址映射
        self.account_address_map = {}

        # 统计信息
        self.checkpoint_stats = {
            'total_verifications': 0,
            'checkpoint_used_count': 0,
            'checkpoint_details': []
        }

    def initialize_environment(self):
        """初始化测试环境"""
        print("="*60)
        print("🚀 持久化多轮测试初始化")
        print("="*60)

        current_round = self.state_manager.get_current_round()
        target_rounds = self.state_manager.get_target_rounds()

        if current_round > 0:
            print(f"📂 检测到已有进度: 第 {current_round}/{target_rounds} 轮")
            print(f"💾 将从第 {current_round + 1} 轮继续运行...")
            print("-"*60)
        else:
            print(f"🆕 开始新的测试: 目标 {target_rounds} 轮")
            print("-"*60)

        # 如果未初始化，创建新的环境
        if not self.state_manager.is_initialized():
            self._create_new_environment()
        else:
            self._load_existing_environment()

    def _create_new_environment(self):
        """创建新的测试环境"""
        print("📁 创建测试环境...")

        # 创建存储目录
        blockchain_dir = os.path.join(self.base_storage_dir, "blockchain")
        account_dir = os.path.join(self.base_storage_dir, "accounts")
        pool_db_path = os.path.join(self.base_storage_dir, "tx_pool.db")

        os.makedirs(blockchain_dir, exist_ok=True)
        os.makedirs(account_dir, exist_ok=True)

        # 保存路径到状态
        self.state_manager.set_storage_paths(blockchain_dir, pool_db_path, account_dir)

        # 创建区块链
        self.config = ChainConfig(
            confirmation_blocks=2,
            max_fork_height=3,
            debug_mode=True,
            data_directory=blockchain_dir,
            auto_save=True  # 启用自动保存
        )
        self.blockchain = Blockchain(config=self.config)

        # 创建交易池
        self.transaction_pool = TxPool(db_path=pool_db_path)

        # 创建交易选择器
        self.transaction_picker = TransactionPicker()

        # 创建账户
        self._create_accounts(account_dir)

        # 创建矿工
        self.miner = Miner(
            miner_id="persistent_test_miner",
            blockchain=self.blockchain
        )

        # 标记为已初始化
        self.state_manager.set_initialized(True)
        self.state_manager.save_state()

        print("✅ 测试环境创建完成")

    def _load_existing_environment(self):
        """加载已有的测试环境"""
        print("📂 加载已有测试环境...")

        blockchain_dir, pool_db_path, account_dir = self.state_manager.get_storage_paths()

        if not all(os.path.exists(p) for p in [blockchain_dir, account_dir]):
            print("❌ 存储目录不完整，需要重新初始化")
            self.state_manager.reset()
            self._create_new_environment()
            return

        # 加载区块链
        self.config = ChainConfig(
            confirmation_blocks=2,
            max_fork_height=3,
            debug_mode=True,
            data_directory=blockchain_dir,
            auto_save=True
        )
        self.blockchain = Blockchain(config=self.config)

        # 加载交易池
        self.transaction_pool = TxPool(db_path=pool_db_path)

        # 创建交易选择器
        self.transaction_picker = TransactionPicker()

        # 加载账户
        self._load_accounts(account_dir)

        # 创建矿工
        self.miner = Miner(
            miner_id="persistent_test_miner",
            blockchain=self.blockchain
        )

        print(f"✅ 测试环境加载完成 | 区块高度: {self.blockchain.get_latest_block_index()}")

    def _create_accounts(self, account_dir: str):
        """创建账户"""
        print("👤 创建账户...")

        account_names = ["alice", "bob", "charlie", "david"]
        accounts_data = []

        for name in account_names:
            private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()
            address = self._create_eth_address(name)

            account = Account(
                address=address,
                private_key_pem=private_key_pem,
                public_key_pem=public_key_pem,
                name=name,
                data_directory=account_dir
            )

            self.accounts.append(account)
            accounts_data.append({
                "name": name,
                "address": address,
                "private_key_pem": private_key_pem,
                "public_key_pem": public_key_pem
            })

        # 保存账户信息
        self.state_manager.set_accounts(accounts_data)

        # 创建地址映射
        self.account_address_map = {account.address: account for account in self.accounts}

        # 初始化创世块
        self._initialize_genesis()

        print(f"✅ 创建 {len(self.accounts)} 个账户")

    def _load_accounts(self, account_dir: str):
        """加载已有账户"""
        print("👤 加载账户...")

        accounts_data = self.state_manager.get_accounts()

        for acc_data in accounts_data:
            account = Account(
                address=acc_data["address"],
                private_key_pem=acc_data["private_key_pem"],
                public_key_pem=acc_data["public_key_pem"],
                name=acc_data["name"],
                data_directory=account_dir
            )
            self.accounts.append(account)

        # 创建地址映射
        self.account_address_map = {account.address: account for account in self.accounts}

        print(f"✅ 加载 {len(self.accounts)} 个账户")

    def _initialize_genesis(self):
        """初始化创世块"""
        print("🌅 初始化创世块...")

        custom_denomination = [
            (1000, 1), (500, 1), (100, 5), (50, 5), (10, 5), (1, 5)
        ]

        genesis_block, unified_submit_tx_info, unified_multi_txn, merkle_tree = create_genesis_block(
            accounts=self.accounts,
            denomination_config=custom_denomination,
            custom_miner="persistent_test_genesis_miner"
        )

        # 添加创世块到区块链
        self.blockchain.add_block(genesis_block)

        # 为每个账户初始化VPB
        for account in self.accounts:
            genesis_values, genesis_proof_units, block_index_result = create_genesis_vpb_for_account(
                account_addr=account.address,
                genesis_block=genesis_block,
                unified_submit_tx_info=unified_submit_tx_info,
                unified_multi_txn=unified_multi_txn,
                merkle_tree=merkle_tree,
                denomination_config=custom_denomination
            )

            account.vpb_manager.initialize_from_genesis_batch(
                genesis_values=genesis_values,
                genesis_proof_units=genesis_proof_units,
                genesis_block_index=block_index_result
            )

        print("✅ 创世块初始化完成")

    def _create_eth_address(self, name: str) -> str:
        """创建以太坊地址"""
        import hashlib
        hash_bytes = hashlib.sha256(name.encode()).digest()
        return f"0x{hash_bytes[:20].hex()}"

    def run_rounds(self, start_round: Optional[int] = None):
        """运行多轮测试"""
        if start_round is None:
            start_round = self.state_manager.get_current_round()

        target_rounds = self.state_manager.get_target_rounds()

        print("="*60)
        print(f"🎯 开始多轮测试 | 轮次: {start_round + 1}-{target_rounds}")
        print("="*60)

        for round_num in range(start_round, target_rounds):
            print(f"\n{'='*60}")
            print(f"🔄 第 {round_num + 1}/{target_rounds} 轮")
            print(f"{'='*60}")

            try:
                self._run_single_round(round_num)

                # 更新轮次
                self.state_manager.increment_round()
                self.state_manager.save_state()

                # 显示当前进度
                self._print_progress()

                # 短暂暂停
                time.sleep(0.5)

            except Exception as e:
                print(f"❌ 第 {round_num + 1} 轮测试失败: {e}")
                import traceback
                traceback.print_exc()
                # 保存当前状态，下次可以继续
                self.state_manager.save_state()
                print(f"💾 当前状态已保存，可以从中断处继续")
                break

        # 完成所有轮次
        if self.state_manager.get_current_round() >= target_rounds:
            print("\n" + "="*60)
            print("🎉 所有测试轮次完成！")
            print("="*60)
            self._print_final_statistics()

    def _run_single_round(self, round_num: int):
        """运行单轮测试"""
        # 步骤1：创建交易
        print("📝 创建交易... | ", end="")
        transaction_requests_list = self._create_transaction_requests()
        total_requests = sum(len(requests) for requests in transaction_requests_list)
        print(f"{len(transaction_requests_list)}轮 {total_requests}笔")

        # 步骤2：从交易请求创建交易
        print("⚡ 创建交易... | ", end="")
        submit_tx_data = self._create_transactions_from_accounts(transaction_requests_list)
        print(f"{len(submit_tx_data)}个交易包")

        if not submit_tx_data:
            print("   ⚠️ 本轮无交易，跳过")
            return

        # 步骤3：提交到交易池
        print("📥 提交交易池... | ", end="")
        added_count = 0
        submit_tx_infos = []

        for submit_tx_info, multi_txn_result, account in submit_tx_data:
            try:
                success = account.submit_tx_infos_to_pool(
                    submit_tx_info=submit_tx_info,
                    tx_pool=self.transaction_pool,
                    multi_txn_result=multi_txn_result
                )
                if success:
                    added_count += 1
                    submit_tx_infos.append(submit_tx_info)
            except Exception as e:
                continue

        print(f"{added_count}/{len(submit_tx_data)} 成功")

        # 步骤4：打包区块
        print("⛏️  打包区块... | ", end="")
        package_data, block, picked_txs_mt_proofs, block_index, sender_addrs = pick_transactions_from_pool_with_proofs(
            tx_pool=self.transaction_pool,
            miner_address=self.miner_address,
            previous_hash=self.blockchain.get_latest_block_hash(),
            block_index=self.blockchain.get_latest_block_index() + 1
        )

        if block and len(package_data.selected_submit_tx_infos) > 0:
            print(f"区块#{block.index} | {len(package_data.selected_submit_tx_infos)}交易")
        else:
            print(f"空区块 #{block.index if block else '?'}")

        # 步骤5：添加区块到区块链
        print("🔗 添加区块... | ", end="")
        main_chain_updated = self.blockchain.add_block(block)
        print(f"{'主链' if main_chain_updated else '分支'}")

        # 步骤6：更新VPB
        if package_data.selected_submit_tx_infos:
            print("🔄 更新VPB...")
            self._update_senders_vpb(package_data, picked_txs_mt_proofs, block)
            self._update_receivers_vpb(package_data)

        # 步骤7：验证状态
        print("✅ 验证状态... | ", end="")
        self._verify_account_states()
        print("通过")

    def _create_transaction_requests(self) -> List[List[Dict]]:
        """创建交易请求"""
        import random

        sender_transaction_groups = {}
        m = random.randint(4, 10)

        # 随机选择发送者-接收者对
        for _ in range(m):
            available_accounts = list(self.accounts)
            sender = random.choice(available_accounts)
            possible_recipients = [acc for acc in available_accounts if acc.address != sender.address]

            if possible_recipients:
                recipient = random.choice(possible_recipients)

                # 检查发送者余额
                unspent_values = sender.get_unspent_values()
                if not unspent_values:
                    continue

                total_balance = sum(v.value_num for v in unspent_values)
                if total_balance <= 0:
                    continue

                # 选择金额
                selected_value = random.choice(unspent_values)
                amount = max(1, min(selected_value.value_num, total_balance))

                nonce = random.randint(10000, 99999) + _ * 100000
                reference = f"tx_{sender.name[:3]}_{recipient.name[:3]}_{_}"

                transaction_request = {
                    "sender": sender.address,
                    "recipient": recipient.address,
                    "amount": amount,
                    "nonce": nonce,
                    "reference": reference
                }

                sender_address = sender.address
                if sender_address not in sender_transaction_groups:
                    sender_transaction_groups[sender_address] = []
                sender_transaction_groups[sender_address].append(transaction_request)

        if not sender_transaction_groups:
            return []

        return list(sender_transaction_groups.values())

    def _create_transactions_from_accounts(self, transaction_requests_list):
        """从交易请求创建交易"""
        submit_tx_data = []

        for round_num, round_requests in enumerate(transaction_requests_list):
            if not round_requests:
                continue

            sender_address = round_requests[0].get("sender")
            sender_account = self.account_address_map.get(sender_address)

            if not sender_account:
                continue

            try:
                total_required_amount = sum(tx.get("amount", 0) for tx in round_requests)
                available_balance = sender_account.get_available_balance()

                if available_balance < total_required_amount:
                    continue

                multi_txn_result = sender_account.create_batch_transactions(
                    transaction_requests=round_requests,
                    reference=f"round_{round_num}_account_{sender_account.name}"
                )

                if multi_txn_result:
                    submit_tx_info = sender_account.create_submit_tx_info(multi_txn_result)
                    if submit_tx_info:
                        submit_tx_data.append((submit_tx_info, multi_txn_result, sender_account))

            except Exception as e:
                continue

        return submit_tx_data

    def _update_senders_vpb(self, package_data, picked_txs_mt_proofs, block):
        """更新发送者VPB"""
        processed_count = 0

        for submit_tx_info in package_data.selected_submit_tx_infos:
            sender_account = self.account_address_map.get(submit_tx_info.submitter_address)
            if not sender_account:
                continue

            # 获取默克尔证明
            merkle_proof = None
            for proof_hash, mt_proof in picked_txs_mt_proofs:
                if proof_hash == submit_tx_info.multi_transactions_hash:
                    merkle_proof = mt_proof
                    break

            multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
            if not multi_txns:
                continue

            total_values = sum(len(txn.value) for txn in multi_txns.multi_txns
                             if hasattr(txn, 'value') and txn.value)

            if total_values > 0:
                primary_recipient = next((txn.recipient for txn in multi_txns.multi_txns
                                       if hasattr(txn, 'recipient') and txn.recipient), "unknown")

                success = sender_account.update_vpb_after_transaction_sent(
                    confirmed_multi_txns=multi_txns,
                    mt_proof=merkle_proof or [],
                    block_height=block.index,
                    recipient_address=primary_recipient
                )

                if success:
                    processed_count += 1

        print(f"   发送者更新: {processed_count}/{len(package_data.selected_submit_tx_infos)}")

    def _update_receivers_vpb(self, package_data):
        """更新接收者VPB"""
        import copy

        total_processed = 0
        verification_success = 0
        receive_success = 0

        # 静默验证器日志
        for logger_name in ['EZ_VPB_Validator', 'EZ_VPB_Validator.VPBSliceGenerator',
                           'EZ_VPB_Validator.DataStructureValidator', 'EZ_VPB_Validator.BloomFilterValidator',
                           'EZ_VPB_Validator.proof_validator', 'EpochExtractor', 'DataStructureValidator',
                           'VPBSliceGenerator', 'BloomFilterValidator', 'VPBValidator']:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)

        for submit_tx_info in package_data.selected_submit_tx_infos:
            sender_account = self.account_address_map.get(submit_tx_info.submitter_address)
            if not sender_account:
                continue

            multi_txns = sender_account.get_submitted_transaction(submit_tx_info.multi_transactions_hash)
            if not multi_txns or not hasattr(multi_txns, 'multi_txns'):
                continue

            for txn in multi_txns.multi_txns:
                recipient_address = getattr(txn, 'recipient', None)
                if not recipient_address:
                    continue

                recipient_account = self.account_address_map.get(recipient_address)
                if not recipient_account:
                    continue

                if hasattr(txn, 'value') and txn.value and len(txn.value) > 0:
                    for single_value in txn.value:
                        transferred_value = copy.deepcopy(single_value)
                        received_proof_units = copy.deepcopy(
                            sender_account.vpb_manager.get_proof_units_for_value(transferred_value)
                        )
                        received_block_index = copy.deepcopy(
                            sender_account.vpb_manager.get_block_index_for_value(transferred_value)
                        )

                        if received_proof_units and received_block_index:
                            total_processed += 1

                            # VPB验证
                            from EZ_VPB_Validator.core.types import MainChainInfo
                            merkle_roots = {}
                            bloom_filters = {}

                            if received_block_index and hasattr(received_block_index, 'index_lst'):
                                for block_height in received_block_index.index_lst:
                                    if block_height == 0:
                                        genesis_block = self.blockchain.get_block_by_index(0)
                                        if genesis_block:
                                            merkle_roots[block_height] = genesis_block.get_m_tree_root()
                                            bloom_filters[block_height] = genesis_block.get_bloom()
                                    else:
                                        block_node = self.blockchain.get_fork_node_by_index(block_height)
                                        if block_node and block_node.block:
                                            merkle_roots[block_height] = block_node.block.get_m_tree_root()
                                            bloom_filters[block_height] = block_node.block.get_bloom()

                            main_chain_info = MainChainInfo(
                                merkle_roots=merkle_roots,
                                bloom_filters=bloom_filters,
                                current_block_height=self.blockchain.get_latest_block_index(),
                                genesis_block_height=0
                            )

                            verification_report = recipient_account.verify_vpb(
                                value=copy.deepcopy(transferred_value),
                                proof_units=copy.deepcopy(received_proof_units),
                                block_index_list=copy.deepcopy(received_block_index),
                                main_chain_info=main_chain_info
                            )

                            # 统计checkpoint使用
                            self.checkpoint_stats['total_verifications'] += 1
                            if verification_report.checkpoint_used:
                                self.checkpoint_stats['checkpoint_used_count'] += 1
                                checkpoint = verification_report.checkpoint_used
                                value_info = f"{checkpoint.value_begin_index[:10]}...({checkpoint.value_num})"
                                self.checkpoint_stats['checkpoint_details'].append({
                                    'round': self.state_manager.get_current_round(),
                                    'account': recipient_account.name,
                                    'block_height': checkpoint.block_height,
                                    'value_info': value_info
                                })

                            if verification_report.is_valid:
                                verification_success += 1
                                receive_success_val = recipient_account.receive_vpb_from_others(
                                    received_value=copy.deepcopy(transferred_value),
                                    received_proof_units=copy.deepcopy(received_proof_units),
                                    received_block_index=copy.deepcopy(received_block_index)
                                )
                                if receive_success_val:
                                    receive_success += 1

        print(f"   接收者更新: {total_processed}个value | 验证:{verification_success} | 接收:{receive_success}")

    def _verify_account_states(self):
        """验证账户状态"""
        for account in self.accounts:
            integrity_valid = account.validate_integrity()
            if not integrity_valid:
                raise ValueError(f"Account {account.name} 完整性验证失败")

    def _print_progress(self):
        """打印当前进度"""
        current_round = self.state_manager.get_current_round()
        target_rounds = self.state_manager.get_target_rounds()

        print(f"\n📊 当前进度: {current_round}/{target_rounds} 轮 ({current_round/target_rounds*100:.1f}%)")

        # 显示账户状态
        total_balance = 0
        account_status = []
        for account in self.accounts:
            account_info = account.get_account_info()
            total_balance += account_info['balances']['total']
            unspent_count = len(account.get_unspent_values())
            confirmed_count = len(account.get_values(ValueState.CONFIRMED))
            account_status.append(f"{account.name}:{account_info['balances']['total']}(U:{unspent_count},C:{confirmed_count})")

        print(f"💰 总余额: {total_balance} | {' | '.join(account_status)}")

        # 显示checkpoint统计
        if self.checkpoint_stats['total_verifications'] > 0:
            checkpoint_rate = (self.checkpoint_stats['checkpoint_used_count'] /
                             self.checkpoint_stats['total_verifications'] * 100)
            print(f"⚡ Checkpoint使用率: {checkpoint_rate:.1f}% ({self.checkpoint_stats['checkpoint_used_count']}/{self.checkpoint_stats['total_verifications']})")

    def _print_final_statistics(self):
        """打印最终统计信息"""
        print("\n" + "="*60)
        print("📈 测试统计信息")
        print("="*60)

        print(f"总轮次: {self.state_manager.get_current_round()}")
        print(f"区块高度: {self.blockchain.get_latest_block_index()}")

        # 账户状态
        print("\n账户最终状态:")
        for account in self.accounts:
            account_info = account.get_account_info()
            unspent_values = account.get_unspent_values()
            confirmed_values = account.get_values(ValueState.CONFIRMED)
            unspent_total = sum(v.value_num for v in unspent_values)
            confirmed_total = sum(v.value_num for v in confirmed_values)

            print(f"  {account.name}:")
            print(f"    总余额: {account_info['balances']['total']}")
            print(f"    UNSPENT: {unspent_total} ({len(unspent_values)}个)")
            print(f"    CONFIRMED: {confirmed_total} ({len(confirmed_values)}个)")

        # Checkpoint统计
        if self.checkpoint_stats['total_verifications'] > 0:
            print(f"\nCheckpoint统计:")
            print(f"  总验证次数: {self.checkpoint_stats['total_verifications']}")
            print(f"  使用checkpoint: {self.checkpoint_stats['checkpoint_used_count']}")
            print(f"  使用率: {self.checkpoint_stats['checkpoint_used_count']/self.checkpoint_stats['total_verifications']*100:.1f}%")

        print("="*60)

    def cleanup(self):
        """清理资源"""
        print("\n🧹 清理资源...")
        for account in self.accounts:
            try:
                account.cleanup()
            except Exception as e:
                logger.warning(f"清理账户 {account.name} 失败: {e}")
        print("✅ 清理完成")


def main():
    """主函数"""
    import argparse

    # 设置编码
    try:
        if sys.platform == "win32":
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            os.environ['PYTHONIOENCODING'] = 'utf-8'
    except:
        pass

    # 解析命令行参数
    parser = argparse.ArgumentParser(description='持久化多轮交易测试')
    parser.add_argument('--rounds', type=int, default=20, help='目标轮次 (默认: 20)')
    parser.add_argument('--reset', action='store_true', help='重置测试状态')
    parser.add_argument('--storage-dir', type=str, default=None, help='存储目录 (默认: EZ_Test/persistent_test_data)')

    args = parser.parse_args()

    # 创建测试器
    tester = PersistentMultiRoundTester(
        base_storage_dir=args.storage_dir,
        target_rounds=args.rounds
    )

    # 如果需要重置
    if args.reset:
        print("🔄 重置测试状态...")
        tester.state_manager.reset()
        print("✅ 重置完成")

    try:
        # 初始化环境
        tester.initialize_environment()

        # 运行测试
        tester.run_rounds()

    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被中断")
        print("💾 当前进度已保存，下次运行将从中断处继续")
        tester.state_manager.save_state()

    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        tester.state_manager.save_state()

    finally:
        tester.cleanup()


if __name__ == "__main__":
    main()