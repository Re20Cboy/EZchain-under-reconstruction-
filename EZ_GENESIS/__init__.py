"""
Legacy V1 genesis compatibility shim.

The physical implementation now lives in `EZ_V1.EZ_GENESIS`.
"""

from EZ_V1.EZ_GENESIS.genesis import (
    GenesisBlockCreator,
    create_genesis_block,
    create_genesis_vpb_for_account,
    validate_genesis_block,
    GENESIS_MINER,
    GENESIS_BLOCK_INDEX,
    DEFAULT_DENOMINATION_CONFIG
)

__all__ = [
    'GenesisBlockCreator',
    'create_genesis_block',
    'create_genesis_vpb_for_account',
    'validate_genesis_block',
    'GENESIS_MINER',
    'GENESIS_BLOCK_INDEX',
    'DEFAULT_DENOMINATION_CONFIG'
]
