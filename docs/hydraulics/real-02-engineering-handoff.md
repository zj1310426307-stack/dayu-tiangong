# REAL-02 Engineering Handoff

## Handoff status

`NOT_READY — REAL-01 DATA REQUIRED`

This document is a gap-controlled handoff shell. It is not a frozen Dataset Version,
solver input approval, calibration certificate, or production authorization.

## Project identity

- Scope: five rivers, two Gates, no Pump Station
- Data owner: missing
- Responsible engineer/reviewer: missing
- Source revision/date: missing
- Controlled evidence index: `real-01-close-source-inventory.yaml`

## Dataset Version

- Authoritative REAL-01 Dataset Version: not created from a complete real package
- Status: not frozen
- Engineering Graph Hash: unavailable
- Reason: only one river centerline and one river cross-section workbook are accessible

## River network summary

- Expected: five uniquely identified rivers with reviewed node/branch topology,
  upstream/downstream direction, confluences/bifurcations, chainage origin, and metre
  engineering CRS.
- Available: one partial Gaoming River centerline source hash.
- Gap: four river sources and the complete connected topology.

## Cross Section summary

- Expected: all five rivers, Branch/Chainage mapping, ordered Station/Elevation points,
  reviewed markers/effective extent, spatial positioning, and per-profile provenance.
- Available: one partial Gaoming River workbook with user-declared 1985 elevation datum.
- Gap: complete coverage, source revision/owner, placement evidence, marker review, and
  professional acceptance.

## Gate parameter summary

No authoritative package is available for either Gate. Each Gate must provide:

- Gate ID, type, Branch and Chainage;
- opening count and net width;
- sill elevation and datum;
- initial/maximum opening and opening/closing speed;
- discharge coefficient and applicability;
- positive/negative inflow, outflow, and free-overflow loss factors;
- structure drawing/source revision and control-rule source;
- reviewer and review decision.

## Boundary and initial-condition summary

- Upstream Q(t): missing. Peak design flow alone is insufficient for unsteady admission.
- Downstream H/H(t) or reviewed rating curve: missing.
- Time basis, timezone, start/end, continuity, units, and applicability: missing.
- Initial water level/discharge or reviewed initialization method: missing.
- Approved scenario definition: missing.

## QA report

Software rules and test evidence are in `real-01-close-validation.md`. No real-data QA
run exists for a complete current engineering graph; therefore `QA_REVIEW` is blocked.

## Source evidence manifest

- `real-01-close-source-inventory.yaml`
- `real-01-close-manifest.yaml`

They are sanitized indexes only. Raw engineering files are not in Git.

## Missing data register

1. Project owner, responsible engineer, source revisions/dates, and review authority.
2. Complete five-river centerlines and node/branch relationship specification.
3. Complete five-river Cross Sections and Branch/Chainage mapping.
4. Authoritative CRS/axis/central-meridian evidence and 1985 datum evidence.
5. Sourced channel/floodplain Manning values for every active profile.
6. Two complete Gate design and operation packages.
7. Upstream Q(t), downstream H/H(t) or rating curve, and time metadata.
8. Scenario and initial-condition evidence.
9. Calibration and independent-validation H/Q series (not required for basic import,
   but required to claim calibration/validation).
10. Trusted reviewer identity/role integration for authorization evidence.

## Assumption register

No missing engineering number was replaced with an assumed value. User-declared
EPSG:4547 and 1985 elevation datum remain `NEEDS_CONFIRMATION` until authoritative
evidence is supplied.

## Review evidence

No authorized engineering review has been completed. No freeze endpoint was called.

## Solver readiness assessment

| Dimension | Status | Meaning |
|---|---|---|
| Engineering data admission | BLOCKED | Complete five-river/two-gate package and QA are missing. |
| MASCARET adapter capability | SEPARATE_EXISTING_CAPABILITY | Does not authorize this incomplete Dataset Version. |
| D-Flow real Pilot data | DEFERRED / DISABLED | No Pilot Execution; production eligibility remains false. |
| Calibration | NOT_READY | Observation data missing. |
| Independent validation | NOT_READY | Independent event/observation evidence missing. |

REAL-02 may begin only after the missing package is supplied, imported through
Preview/Commit, QA passes against the current graph hash, an authorized review occurs,
and the Dataset Version is frozen through the service.
