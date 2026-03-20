"""
Legacy V1 main-chain compatibility shim.

The physical implementation now lives in `EZ_V1.EZ_Main_Chain`.
"""

from EZ_V1.EZ_Main_Chain.Block import Block
from EZ_V1.EZ_Main_Chain.Blockchain import Blockchain, ChainConfig, ConsensusStatus, ForkNode

__all__ = ["Block", "Blockchain", "ChainConfig", "ConsensusStatus", "ForkNode"]
