"""Research-only HYDROLIB-core structure serialization proof.

This module is intentionally outside the production backend and job runner. It
does not execute D-Flow FM and does not claim numerical support.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import types
from pathlib import Path


def _install_netcdf_import_stub() -> None:
    """Allow structure-only imports when the optional NetCDF wheel is absent.

    HYDROLIB-core imports its network writer at package initialization. The
    structure serializer does not call that writer, so the spike may supply the
    constants referenced during import. Any attempt to construct a Dataset still
    fails; this is not a replacement for a full HYDROLIB-core installation.
    """

    module = types.ModuleType("netCDF4")

    class UnavailableDataset:
        """Fail if research code accidentally crosses into network-file I/O."""

        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("NetCDF is unavailable in the structure-only spike")

    module.Dataset = UnavailableDataset
    module.default_fillvals = {
        "i4": -2147483647,
        "i8": -9223372036854775806,
        "f4": 9.96921e36,
        "f8": 9.969209968386869e36,
    }
    sys.modules.setdefault("netCDF4", module)


def serialize_structure_proof(
    output_directory: Path,
    *,
    allow_netcdf_import_stub: bool = False,
) -> dict[str, object]:
    """Serialize and read back one Bridge, Culvert, and Pump definition."""

    if allow_netcdf_import_stub:
        _install_netcdf_import_stub()
    import hydrolib.core
    from hydrolib.core.dflowfm.structure.models import (
        Bridge,
        Culvert,
        Pump,
        StructureModel,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    output_file = output_directory / "structures.ini"
    structures = [
        Bridge(
            id="bridge-proof",
            name="Bridge serialization proof",
            branchId="branch-main",
            chainage=250.0,
            allowedFlowdir="both",
            csDefId="bridge-cs",
            shift=0.0,
            inletLossCoeff=0.5,
            outletLossCoeff=1.0,
            frictionType="Manning",
            friction=0.03,
            length=20.0,
        ),
        Culvert(
            id="culvert-proof",
            name="Culvert serialization proof",
            branchId="branch-main",
            chainage=500.0,
            allowedFlowDir="both",
            leftLevel=0.0,
            rightLevel=-0.1,
            csDefId="culvert-cs",
            length=30.0,
            inletLossCoeff=0.5,
            outletLossCoeff=1.0,
            valveOnOff=False,
            bedFrictionType="Manning",
            bedFriction=0.03,
        ),
        Pump(
            id="pump-proof",
            name="Pump serialization proof",
            branchId="branch-main",
            chainage=750.0,
            orientation="positive",
            capacity=2.5,
        ),
    ]
    StructureModel(structure=structures).save(output_file)
    restored = StructureModel(filepath=output_file)
    restored_types = [item.type for item in restored.structure]
    expected_types = ["bridge", "culvert", "pump"]
    if restored_types != expected_types:
        raise RuntimeError(
            f"HYDROLIB-core structure round trip changed types: {restored_types}"
        )
    content = output_file.read_bytes()
    return {
        "status": "SERIALIZATION_ONLY_PASS",
        "hydrolib_core_version": hydrolib.core.__version__,
        "structure_types": restored_types,
        "output_file": str(output_file.resolve()),
        "sha256": hashlib.sha256(content).hexdigest(),
        "dflow_fm_runtime_executed": False,
        "netcdf_import_stub_used": allow_netcdf_import_stub,
    }


def main() -> int:
    """Run the research proof from an explicitly configured environment."""

    parser = argparse.ArgumentParser()
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--allow-netcdf-import-stub", action="store_true")
    arguments = parser.parse_args()
    result = serialize_structure_proof(
        arguments.output_directory,
        allow_netcdf_import_stub=arguments.allow_netcdf_import_stub,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
