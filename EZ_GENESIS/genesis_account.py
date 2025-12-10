"""
Genesis Account Manager - 创世账户管理器

负责管理创世账户的生成、公私钥管理和初始化配置。
创世账户具有合法的公私钥对，可以执行签名等加密操作。

功能：
1. 生成创世账户的公私钥对
2. 管理创世账户的配置信息
3. 提供创世账户的签名和验证功能
4. 统一创世账户的地址格式和标识
"""

import os
import json
import hashlib
from typing import Dict, Optional, Tuple
from pathlib import Path

from EZ_Tool_Box.SecureSignature import secure_signature_handler


class GenesisAccount:
    """创世账户类，包含完整的账户信息"""

    def __init__(self, address: str, private_key_pem: bytes, public_key_pem: bytes):
        """
        初始化创世账户

        Args:
            address: 账户地址
            private_key_pem: 私钥（PEM格式）
            public_key_pem: 公钥（PEM格式）
        """
        self.address = address
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem
        self.is_genesis = True

    def sign_data(self, data: bytes) -> bytes:
        """使用私钥签名数据"""
        return secure_signature_handler.signer.sign_transaction_data(data, self.private_key_pem)

    def verify_signature(self, data: bytes, signature: bytes) -> bool:
        """验证签名"""
        return secure_signature_handler.signer.verify_signature(data, signature, self.public_key_pem)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'address': self.address,
            'private_key_pem': self.private_key_pem.hex(),
            'public_key_pem': self.public_key_pem.hex(),
            'is_genesis': self.is_genesis
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'GenesisAccount':
        """从字典恢复创世账户"""
        return cls(
            address=data['address'],
            private_key_pem=bytes.fromhex(data['private_key_pem']),
            public_key_pem=bytes.fromhex(data['public_key_pem'])
        )


class GenesisAccountManager:
    """创世账户管理器"""

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化创世账户管理器

        Args:
            config_file: 配置文件路径，如果不提供则使用默认路径
        """
        self.config_file = Path(config_file or "genesis_account.json")
        self.genesis_account: Optional[GenesisAccount] = None
        self._load_or_create_account()

    def _load_or_create_account(self):
        """加载现有账户或创建新账户"""
        if self.config_file.exists():
            try:
                self._load_account()
            except Exception as e:
                print(f"Failed to load genesis account: {e}")
                self._create_new_account()
        else:
            self._create_new_account()

    def _load_account(self):
        """从文件加载创世账户"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.genesis_account = GenesisAccount.from_dict(data)
        print(f"Loaded genesis account: {self.genesis_account.address}")

    def _create_new_account(self):
        """创建新的创世账户"""
        print("Creating new genesis account...")

        # 生成公私钥对
        private_key_pem, public_key_pem = secure_signature_handler.signer.generate_key_pair()

        # 从公钥生成地址
        address = self._generate_address_from_public_key(public_key_pem)

        # 创建创世账户
        self.genesis_account = GenesisAccount(address, private_key_pem, public_key_pem)

        # 保存到文件
        self._save_account()

        print(f"Created new genesis account: {address}")

    def _generate_address_from_public_key(self, public_key_pem: bytes) -> str:
        """从公钥生成账户地址"""
        # 对公钥进行哈希
        public_key_hash = hashlib.sha256(public_key_pem).hexdigest()

        # 添加创世前缀
        genesis_prefix = "0xGENESIS"

        # 生成地址：前缀 + 公钥哈希的前20位
        address = f"{genesis_prefix}{public_key_hash[:20]}"

        return address

    def _save_account(self):
        """保存创世账户到文件"""
        if self.genesis_account:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.genesis_account.to_dict(), f, indent=2)

    def get_genesis_account(self) -> GenesisAccount:
        """获取创世账户"""
        if not self.genesis_account:
            raise RuntimeError("Genesis account not initialized")
        return self.genesis_account

    def get_genesis_address(self) -> str:
        """获取创世账户地址"""
        return self.get_genesis_account().address

    def get_private_key_pem(self) -> bytes:
        """获取创世账户私钥"""
        return self.get_genesis_account().private_key_pem

    def get_public_key_pem(self) -> bytes:
        """获取创世账户公钥"""
        return self.get_genesis_account().public_key_pem

    def is_genesis_address(self, address: str) -> bool:
        """检查地址是否为创世地址"""
        if not self.genesis_account:
            return False
        return address == self.genesis_account.address

    def sign_as_genesis(self, data: bytes) -> bytes:
        """使用创世账户签名数据"""
        return self.get_genesis_account().sign_data(data)

    def verify_genesis_signature(self, data: bytes, signature: bytes) -> bool:
        """验证创世账户的签名"""
        return self.get_genesis_account().verify_signature(data, signature)


# 全局创世账户管理器实例
_global_genesis_manager: Optional[GenesisAccountManager] = None


def get_genesis_manager() -> GenesisAccountManager:
    """获取全局创世账户管理器实例"""
    global _global_genesis_manager
    if _global_genesis_manager is None:
        _global_genesis_manager = GenesisAccountManager()
    return _global_genesis_manager


def get_genesis_account() -> GenesisAccount:
    """获取创世账户"""
    return get_genesis_manager().get_genesis_account()


def get_genesis_address() -> str:
    """获取创世账户地址"""
    return get_genesis_manager().get_genesis_address()