# HYDRO-DATA-REAL-01-CLOSE Final Review

## Acceptance

- Status: `FRAMEWORK_PASS_DATA_REQUIRED`
- Branch: `phase/hydro-data-real-01-close`
- Baseline: `01b01c949b09a0b05434758510080a9e0712edd6`
- Final commit: use the immutable PR head recorded by Git/GitHub
- Real Dataset Version frozen: no
- REAL-02 handoff ready: no

The software changes are conservative and fail closed. The real five-river/two-gate
data package is incomplete and is not represented as a pass. The initially unavailable
Docker Linux engine later recovered; current-head migration and the disposable
PostGIS clone/hash transaction both passed.

## Implemented repairs

1. Required `PARTIAL` domains are freeze blockers instead of warnings.
2. Readiness now checks project identity, full coordinate evidence, legal connected
   topology, Cross Section placement/point order/review, roughness coverage/provenance,
   two complete Gates, true boundary time semantics, scenario/initial conditions, and
   current-graph QA.
3. QA passes persist the current engineering graph hash; stale historical passes do
   not authorize a modified graph.
4. Clone excludes external-model results and all execution/acceptance evidence.
5. Canonical graph identity excludes raw import bytes and clone-only import/case
   display identities; case links use stable clone-independent ordinals.
6. A disposable PostGIS regression test covers real ORM constraints, explicit
   SQL-column/ORM-attribute mappings, FK remapping,
   external-result exclusion, equal hash, and unconditional transaction rollback.

## Changed implementation files

- `backend/app/dataset/engineering_graph.py`
- `backend/app/dataset/real01.py`
- `backend/app/hydraulic/service.py`
- `backend/app/hydraulic/snapshot.py`
- `backend/tests/test_real01_admission.py`
- `backend/tests/test_real01_close_postgis.py`

No API schema, migration, generated client, engine registry, or frontend contract was
changed. The existing frontend already consumes the generated Readiness/Freeze client
and displays domain gaps, hash, Dataset Version state, and fail-closed D-Flow status.

## Real source coverage

Two controlled partial sources were found and hashed:

- one Gaoming River centerline source;
- one Gaoming River Cross Section workbook.

No complete five-river topology, two-gate packages, full boundaries, initial
conditions, scenarios, observations, owner/reviewer evidence, or current-graph QA is
available. Raw files remain outside Git.

## Verification summary

- Ruff changed-file check: PASS.
- REAL-01/Dataset service unit and contract suite: 21 passed.
- Full repository backend/root suite: 512 passed, 77 environment-gated skips.
- Python compile check: PASS.
- Frontend typecheck: PASS.
- Frontend production build: PASS (existing large-chunk warning only).
- Current-head migration and PostGIS clone/hash transaction: PASS; test rolled back
  its fixture and the exact no-volume container was removed.
- Full backend/frontend checks: recorded at PR creation.
- PR CI: recorded by GitHub after push; this review does not predict it.

## Security and permissions

Dataset mutability is fail-closed after approval/freeze, but the application currently
has no trusted current-user/IAM role dependency. The `reviewer` request field is audit
text, not authenticated identity. T14 therefore remains `NOT_RUN`; introducing an ad
hoc token inside this data task would create a misleading security boundary.

## Compatibility

- Existing API response shape is unchanged.
- Existing database schema and historical rows remain readable.
- Clone display names remain unique while canonical engineering identity stays stable.
- Historical QA records without a graph hash remain readable but cannot authorize a
  REAL-01 freeze; a new QA run is required.

## Remaining blockers

See `docs/hydraulics/real-02-engineering-handoff.md`. The immediate next action is for
the engineering data owner to provide the controlled five-river/two-gate package and
review identities; then run Preview/Commit, current-graph QA, authorized review,
freeze, and the PostGIS clone/hash test. No solver run belongs to this task.
