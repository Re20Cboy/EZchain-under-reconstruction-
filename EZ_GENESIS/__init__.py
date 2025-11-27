"""
EZChain Genesis Block Module

This module provides functionality for creating and managing genesis blocks
in the EZChain blockchain system.
"""

from .genesis import (
    GenesisBlockCreator,
    create_genesis_block,
    create_genesis_vpb_for_account,
    validate_genesis_block,
    GENESIS_SENDER,
    GENESIS_MINER,
    GENESIS_BLOCK_INDEX,
    DEFAULT_DENOMINATION_CONFIG
)

__all__ = [
    'GenesisBlockCreator',
    'create_genesis_block',
    'create_genesis_vpb_for_account',
    'validate_genesis_block',
    'GENESIS_SENDER',
    'GENESIS_MINER',
    'GENESIS_BLOCK_INDEX',
    'DEFAULT_DENOMINATION_CONFIG'
]

__version__ = "1.0.0"
__author__ = "EZChain Team"