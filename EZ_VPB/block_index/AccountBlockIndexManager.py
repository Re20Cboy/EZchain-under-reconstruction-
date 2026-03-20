"""
Compatibility shim for the staged V1 migration.
"""

from EZ_V1.EZ_VPB.block_index.AccountBlockIndexManager import (
    AccountBlockIndexManager,
    AccountBlockIndexStorage,
)

__all__ = ["AccountBlockIndexManager", "AccountBlockIndexStorage"]
