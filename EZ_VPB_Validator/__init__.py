"""
EZ_VPB_Validator Package

This package provides a modular VPB (Value-Proofs-BlockIndex) validation system
for EZChain. It breaks down the complex validation process into manageable
steps and utilities for better maintainability and testability.

Core Components:
- Core types and base classes (core/)
- Validation steps (steps/)
- Utility modules (utils/)
- Main validator interface (vpb_validator.py)
"""

from .vpb_validator import VPBValidator
from .core.types import VerificationResult, VerificationError, VPBVerificationReport, MainChainInfo, VPBSlice
from .core.validator_base import ValidatorBase

__version__ = "1.0.0"
__author__ = "EZChain Team"

__all__ = [
    'VPBValidator',
    'VerificationResult',
    'VerificationError',
    'VPBVerificationReport',
    'MainChainInfo',
    'VPBSlice',
    'ValidatorBase'
]