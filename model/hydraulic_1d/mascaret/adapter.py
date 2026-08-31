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
from model.hydraulic_1d.errors import Hydraulic1DValidationError


CASE_FILENAME = "case.xcas"
GEOMETRY_FILENAME = "geometry.geo"
INITIAL_FILENAME = "initial.lig"
RESULT_FILENAME = "results.opt"
MANIFEST_FILENAME = "dayu-mascaret-manifest.json"
MAX_MASCARET_MESH_SECTIONS = 100_000


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


class MascaretModelValidator:
    """Enforce only the MASCARET capabilities verified for the production adapter."""

    def validate(self, model: Hydraulic1DModel) -> None:
        """Reject unsupported topology, structures, roughness, or time-series semantics."""

        if len(model.branches) != 1:
            self._reject(
                "MASCARET_MULTI_BRANCH_NOT_ENABLED",
                "the verified adapter currently accepts exactly one directed Branch",
                "branches",
            )
        if model.structures:
            kinds = ", ".join(sorted({item.kind for item in model.structures}))
            self._reject(
                "MASCARET_STRUCTURE_MAPPING_UNSUPPORTED",
                f"verified production mapping is unavailable for structures: {kinds}",
                "structures",
            )
        branch = model.branches[0]
        endpoints = [item for item in model.boundaries if item.location != "lateral"]
        upstream = [item for item in endpoints if item.location == "upstream"]
        downstream = [item for item in endpoints if item.location == "downstream"]
        if len(upstream) != 1 or upstream[0].variable != "discharge":
            self._reject(
                "MASCARET_UPSTREAM_BOUNDARY_INVALID",
                "one upstream discharge Q(t) boundary is required",
                "boundaries",
            )
        if len(downstream) != 1 or downstream[0].variable != "water_level":
            self._reject(
                "MASCARET_DOWNSTREAM_BOUNDARY_INVALID",
                "one downstream water-level H(t) boundary is required",
                "boundaries",
            )
        if any(item.branch_id != branch.id for item in model.boundaries):
            self._reject(
                "MASCARET_BOUNDARY_BRANCH_MISMATCH",
                "every boundary must belong to the selected Branch",
                "boundaries",
            )
        for index, boundary in enumerate(model.boundaries):
            self._validate_series(boundary, model.settings.duration_seconds, index=index)
            if boundary.variable == "discharge" and any(
                item.value < 0.0 for item in boundary.series
            ):
                self._reject(
                    "MASCARET_NEGATIVE_DISCHARGE_UNVERIFIED",
                    "negative discharge/withdrawal is not enabled by the verified adapter",
                    f"boundaries[{index}].series",
                )
        ratio = model.settings.output_interval_seconds / model.settings.time_step_seconds
        if not isclose(ratio, round(ratio), rel_tol=0.0, abs_tol=1e-9):
            self._reject(
                "MASCARET_OUTPUT_INTERVAL_INVALID",
                "output interval must be an integer multiple of the time step",
                "settings.output_interval_seconds",
            )
        duration_ratio = model.settings.duration_seconds / model.settings.time_step_seconds
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
        sections = self._sections(model, branch)
        minimum_spacing = min(
            right.chainage_m - left.chainage_m
            for left, right in zip(sections, sections[1:])
        )
        estimated_mesh_sections = (
            ceil((branch.end_chainage_m - branch.start_chainage_m) / minimum_spacing) + 1
        )
        if estimated_mesh_sections > MAX_MASCARET_MESH_SECTIONS:
            self._reject(
                "MASCARET_MESH_DENSITY_UNSUPPORTED",
                "minimum Cross Section spacing would exceed the verified mesh-size limit",
                "cross_sections",
            )
        for index, section in enumerate(sections):
            if any(
                not isclose(zone.manning_n, section.manning_n, rel_tol=1e-9, abs_tol=1e-12)
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
        for index, section in enumerate(sections):
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
            or any(section.vertical_datum != vertical_datum for section in sections)
        ):
            self._reject(
                "MASCARET_VERTICAL_DATUM_INVALID",
                "every Cross Section must use the confirmed Network vertical datum",
                "cross_sections",
            )

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
        branch = model.branches[0]
        sections = self.validator._sections(model, branch)
        geometry_path = resolved / GEOMETRY_FILENAME
        initial_path = resolved / INITIAL_FILENAME
        result_path = resolved / RESULT_FILENAME
        manifest_path = resolved / MANIFEST_FILENAME
        geometry_path.write_text(self._geometry(branch, sections), encoding="ascii")
        initial_path.write_text(self._initial(model, sections), encoding="ascii")
        laws, boundary_paths = self._laws(model, resolved)
        case_path = resolved / CASE_FILENAME
        case_path.write_bytes(self._case_xml(model, branch, sections, laws))
        (resolved / "FichierCas.txt").write_text(f"{CASE_FILENAME}\n", encoding="ascii")
        manifest_path.write_text(
            dumps(
                {
                    "schema_version": "dayu.mascaret-manifest.v1",
                    "simulation_id": model.simulation_id,
                    "scenario_id": model.scenario_id,
                    "branch": {"mascaret_id": "1", "dayu_id": branch.id},
                    "cross_sections": [
                        {
                            "mascaret_profile_number": index,
                            "dayu_id": section.id,
                            "code": section.code,
                            "chainage_m": section.chainage_m,
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
        branch: HydraulicBranch,
        sections: list[HydraulicCrossSection],
    ) -> str:
        """Render the official MASCARET geometry grammar with stable ASCII labels."""

        lines: list[str] = []
        for index, section in enumerate(sections, start=1):
            lines.append(f"PROFIL Bief_1 P{index:04d} {section.chainage_m:.12g}")
            for point in section.points:
                kind = "B" if point.zone == "main_channel" else "T"
                lines.append(f"{point.station_m:.12g} {point.elevation_m:.12g} {kind}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _initial(model: Hydraulic1DModel, sections: list[HydraulicCrossSection]) -> str:
        """Render the official LIG initial-state arrays in section order."""

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
        return "\n".join(
            [
                "RESULTATS CALCUL,DATE :  01/01/00 00:00",
                "FICHIER RESULTAT MASCARET",
                "-----------------------------------------------------------------------",
                f" IMAX  = {count:4d} NBBIEF=    1",
                f" I1,I2 =    1 {count:5d}",
                " X",
                " " + " ".join(f"{item.chainage_m:.12g}" for item in sections),
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
    ) -> tuple[list[tuple[int, str, str]], list[Path]]:
        """Write endpoint and lateral boundary laws with unique identifiers."""

        ordered = [
            next(item for item in model.boundaries if item.location == "upstream"),
            next(item for item in model.boundaries if item.location == "downstream"),
            *sorted(
                (item for item in model.boundaries if item.location == "lateral"),
                key=lambda item: float(item.chainage_m or 0.0),
            ),
        ]
        laws: list[tuple[int, str, str]] = []
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
            laws.append((law_id, "1" if boundary.variable == "discharge" else "2", filename))
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
        branch: HydraulicBranch,
        sections: list[HydraulicCrossSection],
        laws: list[tuple[int, str, str]],
    ) -> bytes:
        """Build the v9.1.1 XCAS tree used by the official MASCARET wrapper."""

        root = Element("fichierCas")
        case = self._element(root, "parametresCas")
        general = self._element(case, "parametresGeneraux")
        for name, value in (
            ("versionCode", 3),
            ("code", 3),
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
        steps = round(model.settings.duration_seconds / model.settings.time_step_seconds)
        for name, value in (
            ("pasTemps", model.settings.time_step_seconds),
            ("tempsInit", 0.0),
            ("critereArret", 2),
            ("nbPasTemps", max(1, steps)),
            ("tempsMax", model.settings.duration_seconds),
            ("pasTempsVar", False),
            ("nbCourant", 0.8),
            ("coteMax", 0.0),
            ("abscisseControle", branch.start_chainage_m),
            ("biefControle", 1),
        ):
            self._element(temporal, name, value)
        geometry_network = self._element(case, "parametresGeometrieReseau")
        geometry = self._element(geometry_network, "geometrie")
        self._element(geometry, "fichier", GEOMETRY_FILENAME)
        self._element(geometry, "format", 2)
        self._element(geometry, "profilsAbscAbsolu", True)
        branches = self._element(geometry_network, "listeBranches")
        for name, value in (
            ("nb", 1),
            ("numeros", 1),
            ("abscDebut", branch.start_chainage_m),
            ("abscFin", branch.end_chainage_m),
            ("numExtremDebut", 1),
            ("numExtremFin", 2),
        ):
            self._element(branches, name, value)
        nodes = self._element(geometry_network, "listeNoeuds")
        self._element(nodes, "nb", 0)
        self._element(nodes, "noeuds")
        free = self._element(geometry_network, "extrLibres")
        self._element(free, "nb", 2)
        self._element(free, "num", "1 2")
        self._element(free, "numExtrem", "1 2")
        names = self._element(free, "noms")
        self._element(names, "string", "upstream")
        self._element(names, "string", "downstream")
        self._element(free, "typeCond", "1 2")
        self._element(free, "numLoi", "1 2")
        confluences = self._element(case, "parametresConfluents")
        self._element(confluences, "nbConfluents", 0)
        self._element(confluences, "confluents")
        mesh_group = self._element(case, "parametresPlanimetrageMaillage")
        self._element(mesh_group, "methodeMaillage", 5)
        planimetry = self._element(mesh_group, "planim")
        self._element(planimetry, "nbPas", 101)
        self._element(planimetry, "nbZones", 1)
        self._element(planimetry, "valeursPas", 0.1)
        self._element(planimetry, "num1erProf", 1)
        self._element(planimetry, "numDerProf", len(sections))
        mesh = self._element(mesh_group, "maillage")
        self._element(mesh, "modeSaisie", 2)
        self._element(mesh, "sauvMaillage", False)
        keyboard = self._element(mesh, "maillageClavier")
        spacing = min(
            right.chainage_m - left.chainage_m for left, right in zip(sections, sections[1:])
        )
        self._element(keyboard, "nbSections", 0)
        self._element(keyboard, "nbPlages", 1)
        self._element(keyboard, "num1erProfPlage", 1)
        self._element(keyboard, "numDerProfPlage", len(sections))
        self._element(keyboard, "pasEspacePlage", spacing)
        self._element(keyboard, "nbZones", 0)
        singularity = self._element(case, "parametresSingularite")
        self._element(singularity, "nbSeuils", 0)
        lateral_group = self._element(case, "parametresApportDeversoirs")
        lateral = sorted(
            (item for item in model.boundaries if item.location == "lateral"),
            key=lambda item: float(item.chainage_m or 0.0),
        )
        if lateral:
            inflows = self._element(lateral_group, "debitsApports")
            self._element(inflows, "nbQApport", len(lateral))
            lateral_names = self._element(inflows, "noms")
            for index in range(1, len(lateral) + 1):
                self._element(lateral_names, "string", f"lateral_{index}")
            self._element(inflows, "numBranche", " ".join("1" for _ in lateral))
            self._element(
                inflows,
                "abscisses",
                " ".join(f"{float(item.chainage_m):.12g}" for item in lateral),
            )
            self._element(inflows, "longueurs", " ".join("0.0" for _ in lateral))
            self._element(
                inflows,
                "numLoi",
                " ".join(str(index) for index in range(3, 3 + len(lateral))),
            )
        calibration = self._element(case, "parametresCalage")
        friction = self._element(calibration, "frottement")
        zone_starts: list[float] = []
        zone_ends: list[float] = []
        for index, section in enumerate(sections):
            zone_starts.append(
                branch.start_chainage_m
                if index == 0
                else (sections[index - 1].chainage_m + section.chainage_m) / 2.0
            )
            zone_ends.append(
                branch.end_chainage_m
                if index == len(sections) - 1
                else (section.chainage_m + sections[index + 1].chainage_m) / 2.0
            )
        strickler = [1.0 / section.manning_n for section in sections]
        self._element(friction, "loi", 1)
        self._element(friction, "nbZone", len(sections))
        self._element(friction, "numBranche", " ".join("1" for _ in sections))
        self._element(friction, "absDebZone", " ".join(f"{v:.12g}" for v in zone_starts))
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
        for law_id, law_type, filename in laws:
            law = self._element(laws_node, "structureParametresLoi")
            self._element(law, "nom", f"law_{law_id}")
            self._element(law, "type", law_type)
            data = self._element(law, "donnees")
            self._element(data, "modeEntree", 1)
            self._element(data, "fichier", filename)
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
        self._element(calculated, "variablesCalculees", " ".join("false" for _ in range(15)))
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
        return declaration + b'\n<!DOCTYPE fichierCas SYSTEM "mascaret-1.0.dtd">\n' + xml
