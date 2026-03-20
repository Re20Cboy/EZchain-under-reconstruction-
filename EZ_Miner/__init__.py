"""
Legacy V1 miner compatibility shim.

The physical implementation now lives in `EZ_V1.EZ_Miner`.
"""

from EZ_V1.EZ_Miner.miner import Miner

__all__ = ["Miner"]
