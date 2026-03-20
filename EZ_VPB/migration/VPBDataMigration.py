"""
Compatibility shim for the staged V1 migration.
"""

from EZ_V1.EZ_VPB.migration.VPBDataMigration import VPBDataMigration, main

__all__ = ["VPBDataMigration", "main"]
