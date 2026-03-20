"""
Legacy V1 checkpoint compatibility shim.

The physical implementation now lives in `EZ_V1.EZ_CheckPoint`.
"""

from EZ_V1.EZ_CheckPoint.CheckPoint import CheckPoint, CheckPointRecord, CheckPointStorage

__all__ = ["CheckPoint", "CheckPointRecord", "CheckPointStorage"]
