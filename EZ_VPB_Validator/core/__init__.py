"""
VPB Validator Core Module

Core types and base classes for the VPB validation system.
"""

from .types import VerificationResult, VerificationError, VPBVerificationReport, MainChainInfo, VPBSlice, ValueIntersectionError
from .validator_base import ValidatorBase

__all__ = [
    'VerificationResult',
    'VerificationError',
    'VPBVerificationReport',
    'MainChainInfo',
    'VPBSlice',
    'ValueIntersectionError',
    'ValidatorBase'
]