"""
Legacy V1 VPB validator compatibility shim.

The physical implementation now lives in `EZ_V1.EZ_VPB_Validator`.
"""

from EZ_V1.EZ_VPB_Validator.core.types import MainChainInfo, VPBSlice, VPBVerificationReport, VerificationError, VerificationResult
from EZ_V1.EZ_VPB_Validator.core.validator_base import ValidatorBase
from EZ_V1.EZ_VPB_Validator.vpb_validator import VPBValidator

__all__ = [
    'VPBValidator',
    'VerificationResult',
    'VerificationError',
    'VPBVerificationReport',
    'MainChainInfo',
    'VPBSlice',
    'ValidatorBase'
]
