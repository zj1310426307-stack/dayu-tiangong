"""Compatibility import; the MIKE11 implementation lives at the adapter boundary."""

from app.hydraulic_adapters.mike11_nwk11 import parse_nwk11

__all__ = ["parse_nwk11"]
