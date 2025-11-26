"""
SubmitTxInfo - 提交交易信息

SubmitTxInfo是Account在每轮（每个区块时段内）最终提交至交易池的数据结构。
Account调用CreateMultiTransactions生成MultiTransactions后，在提交至交易池时，
需要基于MultiTransactions生成SubmitTxInfo进行进一步处理。

包含信息：
1. MultiTransactions的哈希值
2. 提交的标准时间戳
3. 当前版本号
4. 提交者地址（MultiTransactions的唯一Sender地址）
5. Sender针对1~4打包信息的数字签名
6. Sender的公钥（用于对签名验证）
"""

import sys
import os
import datetime
import pickle
from typing import Optional, Dict, Any

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(__file__) + '/..')

from EZ_Tool_Box.Hash import sha256_hash
from EZ_Tool_Box.SecureSignature import secure_signature_handler
from EZ_Transaction.MultiTransactions import MultiTransactions


class SubmitTxInfo:
    """
    SubmitTxInfo - 提交交易信息

    包含MultiTransactions的完整提交信息，用于交易池验证和处理。
    """

    # 当前版本号
    VERSION = "1.0.0"

    def __init__(self, multi_transactions: MultiTransactions, private_key_pem: bytes, public_key_pem: bytes):
        """
        初始化SubmitTxInfo，自动生成完整信息

        Args:
            multi_transactions: MultiTransactions实例
            private_key_pem: Sender的私钥（用于签名）
            public_key_pem: Sender的公钥（用于验证）
        """
        # 自动生成所有信息
        self.multi_transactions_hash, self.submit_timestamp, self.version, self.submitter_address, self.signature, self.public_key = self._generate_submit_tx_info(multi_transactions, private_key_pem, public_key_pem)
        self._hash: Optional[str] = None

    def _generate_submit_tx_info(self, multi_transactions: MultiTransactions,
                            private_key_pem: bytes, public_key_pem: bytes) -> tuple:
        """
        生成SubmitTxInfo的所有信息

        Args:
            multi_transactions: MultiTransactions实例
            private_key_pem: Sender的私钥
            public_key_pem: Sender的公钥

        Returns:
            tuple: (multi_transactions_hash, submit_timestamp, version, submitter_address, signature, public_key)
        """
        # 确保MultiTransactions有hash
        if not multi_transactions.digest:
            multi_transactions.set_digest()

        multi_transactions_hash = multi_transactions.digest
        submit_timestamp = datetime.datetime.now().isoformat()
        version = self.VERSION
        submitter_address = multi_transactions.sender

        # 创建签名数据
        signature_data = {
            'multi_transactions_hash': multi_transactions_hash,
            'submit_timestamp': submit_timestamp,
            'version': version,
            'submitter_address': submitter_address
        }

        # 对签名数据进行序列化
        serialized_data = pickle.dumps(signature_data)

        # 使用安全签名处理器进行签名
        signature = secure_signature_handler.signer.sign_transaction_data(serialized_data, private_key_pem)

        return (multi_transactions_hash, submit_timestamp, version, submitter_address, signature, public_key_pem)

    @classmethod
    def create_from_multi_transactions(cls, multi_transactions: MultiTransactions,
                                    private_key_pem: bytes, public_key_pem: bytes) -> 'SubmitTxInfo':
        """
        从MultiTransactions创建SubmitTxInfo的工厂方法

        Args:
            multi_transactions: MultiTransactions实例
            private_key_pem: Sender的私钥
            public_key_pem: Sender的公钥

        Returns:
            SubmitTxInfo: 生成的SubmitTxInfo实例
        """
        return cls(multi_transactions, private_key_pem, public_key_pem)

    def verify(self, multi_transactions: MultiTransactions) -> bool:
        """
        验证SubmitTxInfo

        Args:
            multi_transactions: 用于验证的MultiTransactions实例

        Returns:
            bool: 验证是否通过
        """
        try:
            # 1. 验证MultiTransactions的哈希值
            if not multi_transactions.digest:
                multi_transactions.set_digest()

            if multi_transactions.digest != self.multi_transactions_hash:
                return False

            # 2. 验证提交者地址
            if multi_transactions.sender != self.submitter_address:
                return False

            # 3. 验证版本号
            if self.version != self.VERSION:
                return False

            # 4. 验证时间戳格式
            try:
                datetime.datetime.fromisoformat(self.submit_timestamp)
            except ValueError:
                return False

            # 5. 验证数字签名
            signature_data = {
                'multi_transactions_hash': self.multi_transactions_hash,
                'submit_timestamp': self.submit_timestamp,
                'version': self.version,
                'submitter_address': self.submitter_address
            }
            serialized_data = pickle.dumps(signature_data)

            is_signature_valid = secure_signature_handler.signer.verify_signature(
                serialized_data, self.signature, self.public_key
            )

            return is_signature_valid

        except Exception as e:
            print(f"SubmitTxInfo verification error: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        """
        将SubmitTxInfo转换为字典

        Returns:
            Dict[str, Any]: 序列化后的字典
        """
        return {
            'multi_transactions_hash': self.multi_transactions_hash,
            'submit_timestamp': self.submit_timestamp,
            'version': self.version,
            'submitter_address': self.submitter_address,
            'signature': self.signature.hex() if self.signature else None,
            'public_key': self.public_key.hex() if self.public_key else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SubmitTxInfo':
        """
        从字典恢复SubmitTxInfo实例

        Args:
            data: 包含SubmitTxInfo信息的字典

        Returns:
            SubmitTxInfo: 恢复的SubmitTxInfo实例
        """
        # 创建一个新的SubmitTxInfo实例，但不调用__init__
        instance = cls.__new__(cls)

        # 直接设置属性
        instance.multi_transactions_hash = data['multi_transactions_hash']
        instance.submit_timestamp = data['submit_timestamp']
        instance.version = data['version']
        instance.submitter_address = data['submitter_address']
        instance.signature = bytes.fromhex(data['signature']) if data.get('signature') else None
        instance.public_key = bytes.fromhex(data['public_key']) if data.get('public_key') else None
        instance._hash = None

        return instance

    def get_hash(self) -> str:
        """
        获取SubmitTxInfo的哈希值

        Returns:
            str: SubmitTxInfo的哈希值
        """
        if self._hash is None:
            self._hash = sha256_hash(self.encode())
        return self._hash

    def encode(self) -> bytes:
        """
        编码SubmitTxInfo为字节数据

        Returns:
            bytes: 编码后的字节数据
        """
        return pickle.dumps({
            'multi_transactions_hash': self.multi_transactions_hash,
            'submit_timestamp': self.submit_timestamp,
            'version': self.version,
            'submitter_address': self.submitter_address,
            'signature': self.signature,
            'public_key': self.public_key
        })

    def __str__(self) -> str:
        """
        打印SubmitTxInfo内容

        Returns:
            str: 格式化的字符串表示
        """
        return f"""
SubmitTxInfo:
├── MultiTransactions Hash: {self.multi_transactions_hash}
├── Submit Timestamp: {self.submit_timestamp}
├── Version: {self.version}
├── Submitter Address: {self.submitter_address}
├── Signature: {self.signature.hex()[:32] + '...' if self.signature else 'None'}
├── Public Key: {self.public_key.hex()[:32] + '...' if self.public_key else 'None'}
└── SubmitTxInfo Hash: {self.get_hash()}
""".strip()

    def __repr__(self) -> str:
        """SubmitTxInfo的简洁表示"""
        return f"SubmitTxInfo(hash={self.multi_transactions_hash[:16]}..., submitter={self.submitter_address[:8]}...)"

    def __eq__(self, other) -> bool:
        """判断两个SubmitTxInfo是否相等"""
        if not isinstance(other, SubmitTxInfo):
            return False
        return (self.multi_transactions_hash == other.multi_transactions_hash and
                self.submitter_address == other.submitter_address and
                self.signature == other.signature)