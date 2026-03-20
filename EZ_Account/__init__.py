"""
Legacy V1 account package.

Top-level imports remain for compatibility while the physical implementation
now lives under ``EZ_V1/EZ_Account``.
"""

from .Account import Account

__all__ = ["Account"]
