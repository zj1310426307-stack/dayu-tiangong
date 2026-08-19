"""Compatibility imports; MIKE11 logic is isolated from the hydraulic core."""

from app.hydraulic_adapters.mike11_xns11 import (
    native_xns11_available,
    parse_exchange_subset,
    parse_xns11,
)

__all__ = ["native_xns11_available", "parse_exchange_subset", "parse_xns11"]
