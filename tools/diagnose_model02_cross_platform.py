"""Emit comparable MODEL-02 platform, provenance, and balance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import locale
import platform
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from model import HydraulicEngine
from model.adapters import (
    build_v4_lite_mesh,
    v4_lite_mesh_hash,
    v4_lite_runtime_projection_hash,
    v4_lite_solver_policy_hash,
    v4_lite_validation_policy_hash,
)
from model.api import parse_v4_lite_input
from model.provenance import (
    CANONICALIZATION_ID,
    authoritative_input_hash,
    canonical_json_bytes,
)

_FIXTURE = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "model02"
    / "v4-lite-3-moving-nonprismatic.json"
)
_DEFAULT_OUTPUT = (
    _REPOSITORY_ROOT
    / "outputs"
    / "ci"
    / "model02"
    / "cross-platform-diagnostic.json"
)


def build_diagnostic() -> dict[str, object]:
    """Run the frozen fixture and return separated identity-domain evidence."""

    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    canonical_bytes = canonical_json_bytes(payload)
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    result = HydraulicEngine().run(payload)
    authoritative_hash = authoritative_input_hash(payload)
    if result.provenance.input_snapshot_hash != authoritative_hash:
        raise RuntimeError("result input hash differs from authoritative fixture hash")

    return {
        "platform": platform.platform(),
        "python": sys.version,
        "machine": platform.machine(),
        "libc": list(platform.libc_ver()),
        "locale": list(locale.getlocale()),
        "float_info": {
            "radix": sys.float_info.radix,
            "mant_dig": sys.float_info.mant_dig,
            "epsilon": sys.float_info.epsilon,
        },
        "fixture": _FIXTURE.relative_to(_REPOSITORY_ROOT).as_posix(),
        "canonicalization_id": CANONICALIZATION_ID,
        "canonical_payload_byte_count": len(canonical_bytes),
        "canonical_payload_bytes_sha256": hashlib.sha256(
            canonical_bytes
        ).hexdigest(),
        "authoritative_input_hash": authoritative_hash,
        "runtime_projection_hash": v4_lite_runtime_projection_hash(parsed),
        "mesh_hash": v4_lite_mesh_hash(parsed, mesh),
        "solver_policy_hash": v4_lite_solver_policy_hash(parsed),
        "validation_policy_hash": v4_lite_validation_policy_hash(parsed),
        "water_balance_residual": result.water_balance.water_balance_residual,
        "relative_water_balance_error": (
            result.water_balance.relative_water_balance_error
        ),
        "water_balance_tolerance": result.water_balance.tolerance,
        "water_balance_status": result.water_balance.status,
    }


def main() -> int:
    """Write deterministic JSON for local comparison and CI artifacts."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    diagnostic = build_diagnostic()
    serialized = json.dumps(
        diagnostic,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(serialized + "\n", encoding="utf-8", newline="\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
