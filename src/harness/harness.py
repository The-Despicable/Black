"""
harness.harness — Legacy harness module for test compatibility.

Re-exports HarnessConfig and RaphaelHarness from harness.models.
"""

from harness.models import HarnessConfig, RaphaelHarness

__all__ = ["HarnessConfig", "RaphaelHarness"]
