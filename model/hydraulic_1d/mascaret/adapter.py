"""Translate a validated Dayu model into an isolated MASCARET case workspace."""

from __future__ import annotations

from dataclasses import dataclass
from json import dumps
from math import ceil, isclose
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from model.hydraulic_1d.contracts import (
    BoundaryCondition,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    TimeValue,
)
from model.hydraulic_1d.capabilities import enforce_compatibility
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.network import HydraulicNetworkGraph, HydraulicNetworkValidator
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
)


CASE_FILENAME = "case.xcas"
GEOMETRY_FILENAME = "geometry.geo"
INITIAL_FILENAME = "initial.lig"
RESULT_FILENAME = "results.opt"
MANIFEST_FILENAME = "dayu-mascaret-manifest.json"
MAX_MASCARET_MESH_SECTIONS = 100_000


def mascaret_branch_offsets(
    branches: list[HydraulicBranch],
) -> dict[str, float]:
    """Map branch-local Dayu chainage into non-overlapping native coordinates.

    MASCARET's absolute-profile network reader uses one scalar abscissa namespace.
    Distinct Dayu branches commonly restart at chainage zero, so the adapter gives
    each branch a deterministic private range and reverses it while parsing.
    """

    cursor = 0.0
    offsets: dict[str, float] = {}
    for branch in branches:
        length = branch.end_chainage_m - branch.start_chainage_m
        offsets[branch.id] = cursor - branch.start_chainage_m
        cursor += length + max(1.0, length * 0.01)
    return offsets


@dataclass(frozen=True, slots=True)
class MascaretPreparedCase:
    """Identify all generated source files and the expected raw result."""

    workspace: Path
    case_file: Path
    geometry_file: Path
    initial_file: Path
    result_file: Path
    manifest_file: Path
    boundary_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _MascaretLaw:
    """Bind a generated law number to the Dayu boundary that owns it."""

    law_id: int
    law_type: str
    filename: str
    boundary_id: str


class MascaretModelValidator:
    """Enforce only the MASCARET capabilities verified for the production adapter."""

    def validate(self, model: Hydraulic1DModel) -> None:
        """Reject unsupported topology, structures, roughness, or time-series semantics."""

        graph = HydraulicNetworkValidator().validate(model)
        for node_id in graph.node_ids:
            degree = len(graph.connected_branches(node_id))
            if (
                graph.incoming_branches(node_id)
                and graph.outgoing_branches(node_id)
                and degree != 3
            ):
                self._reject(
                    "MASCARET_NODE_DEGREE_UNSUPPORTED",
                    f"internal node {node_id} requires exactly three native extremities",
                    "branches",
                )
        enforce_compatibility(
            model,
            engine=DEFAULT_HYDRAULIC_1D_ENGINE_ID,
            engine_version=DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
        )
        endpoints = [item for item in model.boundaries if item.location != "lateral"]
        upstream = [item for item in endpoints if item.location == "upstream"]
        downstream = [item for item in endpoints if item.location == "downstream"]
        if not upstream or any(item.variable != "discharge" for item in upstream):
            self._reject(
                "MASCARET_UPSTREAM_BOUNDARY_INVALID",
                "every external upstream boundary must be a discharge Q(t)",
                "boundaries",
            )
        if not downstream or any(item.variable != "water_level" for item in downstream):
            self._reject(
                "MASCARET_DOWNSTREAM_BOUNDARY_INVALID",
                "every external downstream boundary must be a water-level H(t)",
                "boundaries",
            )
        for index, boundary in enumerate(model.boundaries):
            self._validate_series(
                boundary, model.settings.duration_seconds, index=index
            )
            if boundary.variable == "discharge" and any(
                item.value < 0.0 for item in boundary.series
            ):
                self._reject(
                    "MASCARET_NEGATIVE_DISCHARGE_UNVERIFIED",
                    "negative discharge/withdrawal is not enabled by the verified adapter",
                    f"boundaries[{index}].series",
                )
        ratio = (
            model.settings.output_interval_seconds / model.settings.time_step_seconds
        )
        if not isclose(ratio, round(ratio), rel_tol=0.0, abs_tol=1e-9):
            self._reject(
                "MASCARET_OUTPUT_INTERVAL_INVALID",
                "output interval must be an integer multiple of the time step",
                "settings.output_interval_seconds",
            )
        duration_ratio = (
            model.settings.duration_seconds / model.settings.time_step_seconds
        )
        if not isclose(
            duration_ratio,
            round(duration_ratio),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            self._reject(
                "MASCARET_DURATION_INTERVAL_INVALID",
                "simulation duration must be an integer multiple of the time step",
                "settings.duration_seconds",
            )
        ordered_sections: list[HydraulicCrossSection] = []
        estimated_mesh_sections = 0
        for branch in self._branches(model):
            sections = self._sections(model, branch)
            ordered_sections.extend(sections)
            minimum_spacing = min(
                right.chainage_m - left.chainage_m
                for left, right in zip(sections, sections[1:])
            )
            estimated_mesh_sections += (
                ceil(
                    (branch.end_chainage_m - branch.start_chainage_m) / minimum_spacing
                )
                + 1
            )
        if estimated_mesh_sections > MAX_MASCARET_MESH_SECTIONS:
            self._reject(
                "MASCARET_MESH_DENSITY_UNSUPPORTED",
                "Cross Section spacing would exceed the verified network mesh-size limit",
                "cross_sections",
            )
        for index, section in enumerate(ordered_sections):
            if any(
                not isclose(
                    zone.manning_n, section.manning_n, rel_tol=1e-9, abs_tol=1e-12
                )
                for zone in section.roughness_zones
            ):
                self._reject(
                    "MASCARET_TRANSVERSE_ROUGHNESS_UNSUPPORTED",
                    "transverse roughness variation cannot be represented by this mapping",
                    f"cross_sections[{index}].roughness_zones",
                )
        state_map = {
            item.cross_section_id: item for item in model.initial_condition.by_section
        }
        for index, section in enumerate(ordered_sections):
            stage = (
                state_map[section.id].water_level_m
                if state_map
                else model.initial_condition.water_level_m
            )
            assert stage is not None
            minimum_bed = min(item.elevation_m for item in section.points)
            if stage <= minimum_bed:
                self._reject(
                    "MASCARET_INITIAL_STATE_DRY",
                    "initial water level must exceed the local minimum bed elevation",
                    f"cross_sections[{index}]",
                )
        unit = str(model.metadata.get("horizontal_unit", "m"))
        vertical_unit = str(model.metadata.get("vertical_unit", "m"))
        if unit != "m" or vertical_unit != "m":
            self._reject(
                "MASCARET_NON_SI_UNITS_UNSUPPORTED",
                "horizontal and vertical units must both be metres",
                "metadata",
            )
        vertical_datum = str(model.metadata.get("vertical_datum", "")).strip()
        if (
            not vertical_datum
            or vertical_datum.lower() == "unknown"
            or any(
                section.vertical_datum != vertical_datum for section in ordered_sections
            )
        ):
            self._reject(
                "MASCARET_VERTICAL_DATUM_INVALID",
                "every Cross Section must use the confirmed Network vertical datum",
                "cross_sections",
            )
        self._validate_structures(model, graph)

    @staticmethod
    def _branches(model: Hydraulic1DModel) -> list[HydraulicBranch]:
        """Return a deterministic branch order shared by every generated file."""

        return sorted(model.branches, key=lambda item: (item.code, item.id))

    @staticmethod
    def _sections(
        model: Hydraulic1DModel,
        branch: HydraulicBranch,
    ) -> list[HydraulicCrossSection]:
        """Return a deterministic upstream-to-downstream profile order."""

        return sorted(
            (item for item in model.cross_sections if item.branch_id == branch.id),
            key=lambda item: item.chainage_m,
        )

    def _validate_structures(
        self,
        model: Hydraulic1DModel,
        graph: HydraulicNetworkGraph,
    ) -> None:
        """Validate only the fixed geometric weir semantics accepted in v2."""

        del graph
        for index, structure in enumerate(model.structures):
            if structure.status != "active":
                continue
            if structure.kind != "weir":
                # The versioned capability gate normally catches this first. Keep
                # an adapter-local guard in case a future registry is misconfigured.
                self._reject(
                    "MASCARET_STRUCTURE_MAPPING_UNSUPPORTED",
                    f"structure {structure.id} type {structure.kind} has no verified mapping",
                    f"structures[{index}]",
                )
            if structure.hydraulic_law_type != "broad_crested_weir":
                self._reject(
                    "MASCARET_WEIR_LAW_UNSUPPORTED",
                    "verified weirs require hydraulic_law_type=broad_crested_weir",
                    f"structures[{index}].hydraulic_law_type",
                )
            if structure.operation_rule_type != "fixed":
                self._reject(
                    "MASCARET_WEIR_OPERATION_UNSUPPORTED",
                    "verified weirs currently require a fixed operation rule",
                    f"structures[{index}].operation_rule_type",
                )
            for field, positive in (
                ("crest_elevation_m", False),
                ("crest_width_m", True),
                ("discharge_coefficient", True),
            ):
                source = (
                    structure.geometry
                    if field != "discharge_coefficient"
                    else structure.hydraulic_law_parameters
                )
                value = source.get(field)
                if not isinstance(value, (int, float)) or (positive and value <= 0):
                    self._reject(
                        "MASCARET_WEIR_PARAMETERS_INVALID",
                        f"verified geometric weir requires numeric {field}",
                        f"structures[{index}]",
                    )

    def _validate_series(
        self,
        boundary: BoundaryCondition,
        duration_seconds: float,
        *,
        index: int,
    ) -> None:
        """Require a constant or an explicitly covered time series without extrapolation."""

        if len(boundary.series) == 1:
            if boundary.series[0].time_seconds != 0.0:
                self._reject(
                    "MASCARET_BOUNDARY_COVERAGE_INVALID",
                    "a one-sample constant boundary must be declared at t=0",
                    f"boundaries[{index}].series",
                )
            return
        if boundary.series[0].time_seconds != 0.0:
            self._reject(
                "MASCARET_BOUNDARY_COVERAGE_INVALID",
                "time-varying boundary must start at t=0",
                f"boundaries[{index}].series",
            )
        if boundary.series[-1].time_seconds < duration_seconds:
            self._reject(
                "MASCARET_BOUNDARY_COVERAGE_INVALID",
                "time-varying boundary must cover the complete simulation duration",
                f"boundaries[{index}].series",
            )

    @staticmethod
    def _reject(code: str, message: str, field_path: str) -> None:
        """Raise one stable validation error instead of silently degrading the model."""

        raise Hydraulic1DValidationError(code, message, field_path=field_path)


class MascaretModelBuilder:
    """Generate official-style `.xcas/.geo/.loi/.lig` files and a private manifest."""

    def __init__(self, validator: MascaretModelValidator | None = None) -> None:
        """Allow tests and future adapters to supply the same fail-closed validator."""

        self.validator = validator or MascaretModelValidator()

    def build(self, model: Hydraulic1DModel, workspace: Path) -> MascaretPreparedCase:
        """Validate once, then materialize a complete case inside an empty job directory."""

        self.validator.validate(model)
        resolved = workspace.resolve()
        if not resolved.is_dir():
            raise Hydraulic1DValidationError(
                "MASCARET_WORKSPACE_INVALID",
                "job workspace must exist before model generation",
                field_path="workspace",
            )
        branches = self.validator._branches(model)
        branch_offsets = mascaret_branch_offsets(branches)
        sections_by_branch = {
            branch.id: self.validator._sections(model, branch) for branch in branches
        }
        sections = [
            section for branch in branches for section in sections_by_branch[branch.id]
        ]
        geometry_path = resolved / GEOMETRY_FILENAME
        initial_path = resolved / INITIAL_FILENAME
        result_path = resolved / RESULT_FILENAME
        manifest_path = resolved / MANIFEST_FILENAME
        geometry_path.write_text(
            self._geometry(branches, sections_by_branch, branch_offsets),
            encoding="ascii",
        )
        initial_path.write_text(
            self._initial(model, branches, sections_by_branch, branch_offsets),
            encoding="ascii",
        )
        laws, boundary_paths = self._laws(model, resolved)
        case_path = resolved / CASE_FILENAME
        case_path.write_bytes(
            self._case_xml(
                model,
                branches,
                sections_by_branch,
                laws,
                branch_offsets,
            )
        )
        # The native Fortran runtime reads this indirection file directly. The
        # official launcher writes a single-quoted steering-file basename.
        (resolved / "FichierCas.txt").write_text(
            f"'{CASE_FILENAME}'\n",
            encoding="ascii",
        )
        manifest_path.write_text(
            dumps(
                {
                    "schema_version": "dayu.mascaret-manifest.v2",
                    "simulation_id": model.simulation_id,
                    "scenario_id": model.scenario_id,
                    "branches": [
                        {"mascaret_id": str(index), "dayu_id": branch.id}
                        for index, branch in enumerate(branches, start=1)
                    ],
                    "cross_sections": [
                        {
                            "mascaret_profile_number": index,
                            "mascaret_branch_number": next(
                                branch_index
                                for branch_index, branch in enumerate(branches, start=1)
                                if branch.id == section.branch_id
                            ),
                            "dayu_id": section.id,
                            "code": section.code,
                            "chainage_m": section.chainage_m,
                            "mascaret_chainage_m": (
                                section.chainage_m + branch_offsets[section.branch_id]
                            ),
                        }
                        for index, section in enumerate(sections, start=1)
                    ],
                    "result_file": RESULT_FILENAME,
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="ascii",
        )
        return MascaretPreparedCase(
            workspace=resolved,
            case_file=case_path,
            geometry_file=geometry_path,
            initial_file=initial_path,
            result_file=result_path,
            manifest_file=manifest_path,
            boundary_files=tuple(boundary_paths),
        )

    @staticmethod
    def _geometry(
        branches: list[HydraulicBranch],
        sections_by_branch: dict[str, list[HydraulicCrossSection]],
        branch_offsets: dict[str, float],
    ) -> str:
        """Render the official MASCARET geometry grammar with stable ASCII labels."""

        lines: list[str] = []
        profile_number = 0
        for branch_number, branch in enumerate(branches, start=1):
            for section in sections_by_branch[branch.id]:
                profile_number += 1
                lines.append(
                    f"PROFIL Bief_{branch_number} P{profile_number:04d} "
                    f"{section.chainage_m + branch_offsets[branch.id]:.12g}"
                )
                for point in section.points:
                    kind = "B" if point.zone == "main_channel" else "T"
                    lines.append(
                        f"{point.station_m:.12g} {point.elevation_m:.12g} {kind}"
                    )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _initial(
        model: Hydraulic1DModel,
        branches: list[HydraulicBranch],
        sections_by_branch: dict[str, list[HydraulicCrossSection]],
        branch_offsets: dict[str, float],
    ) -> str:
        """Render the official LIG initial-state arrays in section order."""

        sections = [
            section for branch in branches for section in sections_by_branch[branch.id]
        ]
        state_map = {
            item.cross_section_id: item for item in model.initial_condition.by_section
        }
        stages = [
            state_map[item.id].water_level_m
            if state_map
            else model.initial_condition.water_level_m
            for item in sections
        ]
        flows = [
            state_map[item.id].discharge_m3s
            if state_map
            else model.initial_condition.discharge_m3s
            for item in sections
        ]
        count = len(sections)
        ranges: list[int] = []
        first = 1
        for branch in branches:
            last = first + len(sections_by_branch[branch.id]) - 1
            ranges.extend((first, last))
            first = last + 1
        return "\n".join(
            [
                "RESULTATS CALCUL,DATE :  01/01/00 00:00",
                "FICHIER RESULTAT MASCARET",
                "-----------------------------------------------------------------------",
                f" IMAX  = {count:4d} NBBIEF= {len(branches):4d}",
                " I1,I2 = " + " ".join(f"{value:5d}" for value in ranges),
                " X",
                " "
                + " ".join(
                    f"{item.chainage_m + branch_offsets[item.branch_id]:.12g}"
                    for item in sections
                ),
                " Z",
                " " + " ".join(f"{float(item):.12g}" for item in stages),
                " Q",
                " " + " ".join(f"{float(item):.12g}" for item in flows),
                " FIN",
                "",
            ]
        )

    @staticmethod
    def _expanded_series(
        series: tuple[TimeValue, ...],
        duration_seconds: float,
    ) -> tuple[TimeValue, ...]:
        """Expand a true constant into the two samples required by a `.loi` file."""

        if len(series) > 1:
            return series
        return (
            TimeValue(time_seconds=0.0, value=series[0].value),
            TimeValue(time_seconds=duration_seconds, value=series[0].value),
        )

    def _laws(
        self,
        model: Hydraulic1DModel,
        workspace: Path,
    ) -> tuple[list[_MascaretLaw], list[Path]]:
        """Write endpoint and lateral boundary laws with unique identifiers."""

        branch_rank = {
            branch.id: index
            for index, branch in enumerate(self.validator._branches(model))
        }
        location_rank = {"upstream": 0, "downstream": 1, "lateral": 2}
        ordered = sorted(
            model.boundaries,
            key=lambda item: (
                location_rank[item.location],
                branch_rank[item.branch_id],
                float(item.chainage_m or -1.0),
                item.id,
            ),
        )
        laws: list[_MascaretLaw] = []
        paths: list[Path] = []
        for law_id, boundary in enumerate(ordered, start=1):
            filename = f"law-{law_id:03d}.loi"
            name = "hydrogramme" if boundary.variable == "discharge" else "limnigramme"
            ordinate = "Debit" if boundary.variable == "discharge" else "Cote"
            lines = [f"# law_{law_id}_{name}", f"# Temps (s) {ordinate}", "         S"]
            lines.extend(
                f" {item.time_seconds:.12g} {item.value:.12g}"
                for item in self._expanded_series(
                    boundary.series,
                    model.settings.duration_seconds,
                )
            )
            path = workspace / filename
            path.write_text("\n".join(lines) + "\n", encoding="ascii")
            laws.append(
                _MascaretLaw(
                    law_id=law_id,
                    law_type="1" if boundary.variable == "discharge" else "2",
                    filename=filename,
                    boundary_id=boundary.id,
                )
            )
            paths.append(path)
        return laws, paths

    @staticmethod
    def _element(parent: Element, name: str, value: object | None = None) -> Element:
        """Create one XML node while preserving explicit false/zero values."""

        child = SubElement(parent, name)
        if value is not None:
            if isinstance(value, bool):
                child.text = "true" if value else "false"
            else:
                child.text = str(value)
        return child

    def _case_xml(
        self,
        model: Hydraulic1DModel,
        branches: list[HydraulicBranch],
        sections_by_branch: dict[str, list[HydraulicCrossSection]],
        laws: list[_MascaretLaw],
        branch_offsets: dict[str, float],
    ) -> bytes:
        """Build the v9.1.1 XCAS tree used by the official MASCARET wrapper."""

        root = Element("fichierCas")
        case = self._element(root, "parametresCas")
        general = self._element(case, "parametresGeneraux")
        has_active_weir = any(
            item.kind == "weir" and item.status == "active" for item in model.structures
        )
        kernel_code = (
            2
            if has_active_weir or model.metadata.get("mascaret_kernel") == "rezo"
            else 3
        )
        for name, value in (
            ("versionCode", 3),
            ("code", kernel_code),
            ("fichMotsCles", CASE_FILENAME),
            ("dictionaire", "dico.txt"),
            ("progPrincipal", "princi.f"),
            ("sauveModele", False),
            ("fichSauvModele", "case.tmp"),
            ("validationCode", False),
            ("typeValidation", 1),
            ("presenceCasiers", False),
        ):
            self._element(general, name, value)
        libraries = self._element(general, "bibliotheques")
        self._element(libraries, "bibliotheque", "mascaretV5P1.a damoV3P0.a")
        physical = self._element(case, "parametresModelePhysique")
        self._element(physical, "perteChargeConf", False)
        self._element(physical, "compositionLits", 1)
        self._element(physical, "conservFrotVertical", False)
        self._element(physical, "elevCoteArrivFront", 0.05)
        self._element(physical, "interpolLinStrickler", False)
        overflow = self._element(physical, "debordement")
        self._element(overflow, "litMajeur", False)
        self._element(overflow, "zoneStock", False)
        numerical = self._element(case, "parametresNumeriques")
        for name, value in (
            ("calcOndeSubmersion", False),
            ("decentrement", False),
            ("froudeLimCondLim", 1000.0),
            ("traitImplicitFrot", False),
            ("hauteurEauMini", 0.005),
            ("implicitNoyauTrans", False),
            ("optimisNoyauTrans", False),
            ("perteChargeAutoElargissement", False),
            ("termesNonHydrostatiques", False),
            ("apportDebit", 0),
            ("attenuationConvection", False),
        ):
            self._element(numerical, name, value)
        temporal = self._element(case, "parametresTemporels")
        steps = round(
            model.settings.duration_seconds / model.settings.time_step_seconds
        )
        for name, value in (
            ("pasTemps", model.settings.time_step_seconds),
            ("tempsInit", 0.0),
            ("critereArret", 2),
            ("nbPasTemps", max(1, steps)),
            ("tempsMax", model.settings.duration_seconds),
            ("pasTempsVar", False),
            ("nbCourant", 0.8),
            ("coteMax", 0.0),
            (
                "abscisseControle",
                branches[0].start_chainage_m + branch_offsets[branches[0].id],
            ),
            ("biefControle", 1),
        ):
            self._element(temporal, name, value)
        geometry_network = self._element(case, "parametresGeometrieReseau")
        geometry = self._element(geometry_network, "geometrie")
        self._element(geometry, "fichier", GEOMETRY_FILENAME)
        self._element(geometry, "format", 2)
        self._element(geometry, "profilsAbscAbsolu", True)
        branch_number = {
            branch.id: index for index, branch in enumerate(branches, start=1)
        }
        graph = HydraulicNetworkGraph(model)
        branches_node = self._element(geometry_network, "listeBranches")
        for name, value in (
            ("nb", len(branches)),
            ("numeros", " ".join(str(index) for index in range(1, len(branches) + 1))),
            (
                "abscDebut",
                " ".join(
                    f"{item.start_chainage_m + branch_offsets[item.id]:.12g}"
                    for item in branches
                ),
            ),
            (
                "abscFin",
                " ".join(
                    f"{item.end_chainage_m + branch_offsets[item.id]:.12g}"
                    for item in branches
                ),
            ),
            (
                "numExtremDebut",
                " ".join(str(2 * index - 1) for index in range(1, len(branches) + 1)),
            ),
            (
                "numExtremFin",
                " ".join(str(2 * index) for index in range(1, len(branches) + 1)),
            ),
        ):
            self._element(branches_node, name, value)
        internal_node_ids = [
            node_id
            for node_id in graph.node_ids
            if graph.incoming_branches(node_id) and graph.outgoing_branches(node_id)
        ]
        nodes = self._element(geometry_network, "listeNoeuds")
        self._element(nodes, "nb", len(internal_node_ids))
        node_items = self._element(nodes, "noeuds")
        for node_id in internal_node_ids:
            endpoint_numbers = [
                2 * branch_number[item.id] for item in graph.incoming_branches(node_id)
            ] + [
                2 * branch_number[item.id] - 1
                for item in graph.outgoing_branches(node_id)
            ]
            endpoint_numbers.extend(0 for _ in range(5 - len(endpoint_numbers)))
            node = self._element(node_items, "noeud")
            self._element(
                node, "num", " ".join(str(value) for value in endpoint_numbers)
            )
        law_by_boundary = {item.boundary_id: item for item in laws}
        endpoint_boundaries = sorted(
            (item for item in model.boundaries if item.location != "lateral"),
            key=lambda item: (
                0 if item.location == "upstream" else 1,
                branch_number[item.branch_id],
                item.id,
            ),
        )
        free = self._element(geometry_network, "extrLibres")
        self._element(free, "nb", len(endpoint_boundaries))
        self._element(
            free,
            "num",
            " ".join(str(index) for index in range(1, len(endpoint_boundaries) + 1)),
        )
        self._element(
            free,
            "numExtrem",
            " ".join(
                str(
                    2 * branch_number[item.branch_id] - 1
                    if item.location == "upstream"
                    else 2 * branch_number[item.branch_id]
                )
                for item in endpoint_boundaries
            ),
        )
        names = self._element(free, "noms")
        for item in endpoint_boundaries:
            self._element(names, "string", item.id)
        self._element(
            free,
            "typeCond",
            " ".join(
                "1" if item.variable == "discharge" else "2"
                for item in endpoint_boundaries
            ),
        )
        self._element(
            free,
            "numLoi",
            " ".join(
                str(law_by_boundary[item.id].law_id) for item in endpoint_boundaries
            ),
        )
        confluences = self._element(case, "parametresConfluents")
        self._element(confluences, "nbConfluents", len(internal_node_ids))
        confluence_items = self._element(confluences, "confluents")
        for node_id in internal_node_ids:
            incident = [
                *graph.incoming_branches(node_id),
                *graph.outgoing_branches(node_id),
            ]
            degree = len(incident)
            confluence = self._element(confluence_items, "structureParametresConfluent")
            self._element(confluence, "nbAffluent", degree)
            self._element(confluence, "nom", node_id)
            maximum_profile_width = max(
                section.points[-1].station_m - section.points[0].station_m
                for branch in incident
                for section in sections_by_branch[branch.id]
            )
            scale = maximum_profile_width / 0.8
            # MASCARET constructs a local 2D hexagon and requires its six faces
            # to be counter-clockwise. This normalized three-arm layout follows
            # the official v9.1.1 confluence example and is scaled to the widest
            # incident surveyed profile.
            abscissas = (-0.3608 * scale, 0.2165 * scale, 0.05 * scale)
            ordinates = (0.0, 0.0, 0.59 * scale)
            angles = (180.0, 0.0, 60.0)
            self._element(
                confluence,
                "abscisses",
                " ".join(f"{value:.12g}" for value in abscissas),
            )
            self._element(
                confluence,
                "ordonnees",
                " ".join(f"{value:.12g}" for value in ordinates),
            )
            self._element(
                confluence, "angles", " ".join(f"{angle:.12g}" for angle in angles)
            )
        profile_ranges: list[tuple[int, int]] = []
        profile_index = 1
        for item in branches:
            last = profile_index + len(sections_by_branch[item.id]) - 1
            profile_ranges.append((profile_index, last))
            profile_index = last + 1
        mesh_group = self._element(case, "parametresPlanimetrageMaillage")
        self._element(mesh_group, "methodeMaillage", 5)
        planimetry = self._element(mesh_group, "planim")
        self._element(planimetry, "nbPas", 101)
        self._element(planimetry, "nbZones", len(branches))
        self._element(planimetry, "valeursPas", " ".join("0.1" for _ in branches))
        self._element(
            planimetry,
            "num1erProf",
            " ".join(str(first) for first, _ in profile_ranges),
        )
        self._element(
            planimetry, "numDerProf", " ".join(str(last) for _, last in profile_ranges)
        )
        mesh = self._element(mesh_group, "maillage")
        self._element(mesh, "modeSaisie", 2)
        self._element(mesh, "sauvMaillage", False)
        keyboard = self._element(mesh, "maillageClavier")
        spacing = [
            min(
                right.chainage_m - left.chainage_m
                for left, right in zip(
                    sections_by_branch[item.id], sections_by_branch[item.id][1:]
                )
            )
            for item in branches
        ]
        self._element(keyboard, "nbSections", 0)
        self._element(keyboard, "nbPlages", len(branches))
        self._element(
            keyboard,
            "num1erProfPlage",
            " ".join(str(first) for first, _ in profile_ranges),
        )
        self._element(
            keyboard,
            "numDerProfPlage",
            " ".join(str(last) for _, last in profile_ranges),
        )
        self._element(
            keyboard, "pasEspacePlage", " ".join(f"{value:.12g}" for value in spacing)
        )
        self._element(keyboard, "nbZones", 0)
        singularity = self._element(case, "parametresSingularite")
        weirs = sorted(
            (
                item
                for item in model.structures
                if item.status == "active" and item.kind == "weir"
            ),
            key=lambda item: (branch_number[item.branch_id], item.chainage_m, item.id),
        )
        self._element(singularity, "nbSeuils", len(weirs))
        if weirs:
            weir_items = self._element(singularity, "seuils")
            for item in weirs:
                crest = float(item.geometry["crest_elevation_m"])
                width = float(item.geometry["crest_width_m"])
                coefficient = float(
                    item.hydraulic_law_parameters["discharge_coefficient"]
                )
                weir = self._element(weir_items, "structureParametresSeuil")
                for name, value in (
                    ("nom", item.id),
                    ("type", 3),
                    ("numBranche", branch_number[item.branch_id]),
                    (
                        "abscisse",
                        item.chainage_m + branch_offsets[item.branch_id],
                    ),
                    ("coteCrete", "-0"),
                    ("coteCreteMoy", crest),
                    ("coteRupture", 10000.0),
                    ("coeffDebit", coefficient),
                    ("largVanne", "-0"),
                    ("numLoi", "-0"),
                    ("nbPtLoiSeuil", 2),
                    ("abscTravCrete", f"0 {width:.12g}"),
                    ("cotesCrete", f"{crest:.12g} {crest:.12g}"),
                    ("epaisseur", 1),
                    ("gradient", "-0"),
                ):
                    self._element(weir, name, value)
        lateral_group = self._element(case, "parametresApportDeversoirs")
        lateral = sorted(
            (item for item in model.boundaries if item.location == "lateral"),
            key=lambda item: (
                branch_number[item.branch_id],
                float(item.chainage_m or 0.0),
                item.id,
            ),
        )
        if lateral:
            inflows = self._element(lateral_group, "debitsApports")
            self._element(inflows, "nbQApport", len(lateral))
            lateral_names = self._element(inflows, "noms")
            for index in range(1, len(lateral) + 1):
                self._element(lateral_names, "string", f"lateral_{index}")
            self._element(
                inflows,
                "numBranche",
                " ".join(str(branch_number[item.branch_id]) for item in lateral),
            )
            self._element(
                inflows,
                "abscisses",
                " ".join(
                    f"{float(item.chainage_m) + branch_offsets[item.branch_id]:.12g}"
                    for item in lateral
                ),
            )
            self._element(inflows, "longueurs", " ".join("0.0" for _ in lateral))
            self._element(
                inflows,
                "numLoi",
                " ".join(str(law_by_boundary[item.id].law_id) for item in lateral),
            )
        calibration = self._element(case, "parametresCalage")
        friction = self._element(calibration, "frottement")
        zone_starts: list[float] = []
        zone_ends: list[float] = []
        friction_branch_numbers: list[int] = []
        all_sections: list[HydraulicCrossSection] = []
        for item in branches:
            sections = sections_by_branch[item.id]
            all_sections.extend(sections)
            friction_branch_numbers.extend(branch_number[item.id] for _ in sections)
            for index, section in enumerate(sections):
                zone_starts.append(
                    item.start_chainage_m + branch_offsets[item.id]
                    if index == 0
                    else (sections[index - 1].chainage_m + section.chainage_m) / 2.0
                    + branch_offsets[item.id]
                )
                zone_ends.append(
                    item.end_chainage_m + branch_offsets[item.id]
                    if index == len(sections) - 1
                    else (section.chainage_m + sections[index + 1].chainage_m) / 2.0
                    + branch_offsets[item.id]
                )
        strickler = [1.0 / section.manning_n for section in all_sections]
        self._element(friction, "loi", 1)
        self._element(friction, "nbZone", len(all_sections))
        self._element(
            friction,
            "numBranche",
            " ".join(str(value) for value in friction_branch_numbers),
        )
        self._element(
            friction, "absDebZone", " ".join(f"{v:.12g}" for v in zone_starts)
        )
        self._element(friction, "absFinZone", " ".join(f"{v:.12g}" for v in zone_ends))
        self._element(friction, "coefLitMin", " ".join(f"{v:.12g}" for v in strickler))
        self._element(friction, "coefLitMaj", " ".join(f"{v:.12g}" for v in strickler))
        storage = self._element(calibration, "zoneStockage")
        self._element(storage, "nbProfils", 0)
        self._element(storage, "numProfil", "-0")
        self._element(storage, "limGauchLitMaj", "-0")
        self._element(storage, "limDroitLitMaj", "-0")
        laws_group = self._element(case, "parametresLoisHydrauliques")
        self._element(laws_group, "nb", len(laws))
        laws_node = self._element(laws_group, "lois")
        for law_item in laws:
            law = self._element(laws_node, "structureParametresLoi")
            self._element(law, "nom", f"law_{law_item.law_id}")
            self._element(law, "type", law_item.law_type)
            data = self._element(law, "donnees")
            self._element(data, "modeEntree", 1)
            self._element(data, "fichier", law_item.filename)
            self._element(data, "uniteTps", "-0")
            self._element(data, "nbPoints", "-0")
            self._element(data, "nbDebitsDifferents", "-0")
        initial = self._element(case, "parametresConditionsInitiales")
        restart = self._element(initial, "repriseEtude")
        self._element(restart, "repriseCalcul", False)
        waterline = self._element(initial, "ligneEau")
        self._element(waterline, "LigEauInit", True)
        self._element(waterline, "modeEntree", 1)
        self._element(waterline, "fichLigEau", INITIAL_FILENAME)
        self._element(waterline, "formatFichLig", 2)
        self._element(waterline, "nbPts", "-0")
        printing = self._element(case, "parametresImpressionResultats")
        self._element(printing, "titreCalcul", "Dayu hydraulic 1D")
        flags = self._element(printing, "impression")
        for name in (
            "impressionGeometrie",
            "impressionPlanimetrage",
            "impressionReseau",
            "impressionLoiHydraulique",
            "impressionligneEauInitiale",
            "impressionCalcul",
        ):
            self._element(flags, name, False)
        storage_steps = self._element(printing, "pasStockage")
        self._element(storage_steps, "premPasTpsStock", 1)
        output_steps = round(
            model.settings.output_interval_seconds / model.settings.time_step_seconds
        )
        self._element(storage_steps, "pasStock", max(1, output_steps))
        self._element(storage_steps, "pasImpression", max(1, output_steps))
        results = self._element(printing, "resultats")
        self._element(results, "fichResultat", RESULT_FILENAME)
        self._element(results, "postProcesseur", 2)
        listing = self._element(printing, "listing")
        self._element(listing, "fichListing", "results.lis")
        restart_file = self._element(printing, "fichReprise")
        self._element(restart_file, "fichRepriseEcr", "results.rep")
        rubens = self._element(printing, "rubens")
        self._element(rubens, "ecartInterBranch", 1.0)
        result_storage = self._element(printing, "stockage")
        self._element(result_storage, "option", 1)
        self._element(result_storage, "nbSite", 0)
        calculated = self._element(case, "parametresVariablesCalculees")
        self._element(
            calculated, "variablesCalculees", " ".join("false" for _ in range(15))
        )
        stored = self._element(case, "parametresVariablesStockees")
        stored_positions = {1, 6, 7, 8, 9, 10, 11, 13, 14, 16, 17, 18, 19, 20, 21, 23}
        self._element(
            stored,
            "variablesStockees",
            " ".join(
                "true" if position in stored_positions else "false"
                for position in range(1, 43)
            ),
        )
        indent(root, space="  ")
        body = tostring(root, encoding="iso-8859-1", xml_declaration=True)
        declaration, xml = body.split(b"\n", 1)
        return (
            declaration + b'\n<!DOCTYPE fichierCas SYSTEM "mascaret-1.0.dtd">\n' + xml
        )
