"""MASCARET adapter implementation behind the unified Dayu 1D engine contract."""

from model.hydraulic_1d.mascaret.config import (
    MASCARET_ENGINE_ID,
    MASCARET_RUNTIME_SKIP_REASON,
    MASCARET_SOURCE_ARCHIVE_SHA256,
    MASCARET_UPSTREAM_COMMIT,
    MASCARET_UPSTREAM_TAG,
    MASCARET_VERSION,
    MascaretRuntimeConfig,
)
from model.hydraulic_1d.mascaret.adapter import (
    MascaretModelBuilder,
    MascaretModelValidator,
    MascaretPreparedCase,
)
from model.hydraulic_1d.mascaret.engine import MascaretEngine
from model.hydraulic_1d.mascaret.parser import MascaretResultParser
from model.hydraulic_1d.mascaret.runtime import (
    CliMascaretRuntime,
    ContainerMascaretRuntime,
    MascaretRuntime,
    MascaretRuntimeIdentity,
    MascaretRuntimeRequest,
    MascaretRuntimeResult,
    create_mascaret_runtime,
)
from model.hydraulic_1d.mascaret.workspace import MascaretJobWorkspace

__all__ = [
    "MASCARET_ENGINE_ID",
    "MASCARET_RUNTIME_SKIP_REASON",
    "MASCARET_SOURCE_ARCHIVE_SHA256",
    "MASCARET_UPSTREAM_COMMIT",
    "MASCARET_UPSTREAM_TAG",
    "MASCARET_VERSION",
    "CliMascaretRuntime",
    "ContainerMascaretRuntime",
    "MascaretEngine",
    "MascaretJobWorkspace",
    "MascaretModelBuilder",
    "MascaretModelValidator",
    "MascaretPreparedCase",
    "MascaretResultParser",
    "MascaretRuntime",
    "MascaretRuntimeConfig",
    "MascaretRuntimeIdentity",
    "MascaretRuntimeRequest",
    "MascaretRuntimeResult",
    "create_mascaret_runtime",
]
