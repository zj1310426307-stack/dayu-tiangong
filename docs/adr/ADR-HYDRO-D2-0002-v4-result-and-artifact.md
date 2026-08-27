# ADR-HYDRO-D2-0002: v4 Result Persistence and Evidence Artifact

- Status: accepted
- Date: 2026-08-28

## Context

The D1 runtime returns dense SSP-RK stage evidence and output-interval hydraulic
series. Legacy `simulation_result` and `structure_result` reference public
compatibility identities and cannot represent the native-v4 provenance contract.
Writing every stage to ordinary relational rows would also make the task database an
unbounded evidence store.

## Decision

1. Publish platform results as `dayu.hydraulic-result.v3`; never relabel them as v2.
2. Persist output-interval Section, Gate, Pump, and accepted control-event rows in
   additive tables using authoritative hydraulic/Dataset Version identities.
3. Keep all Gate/Pump RK-stage evidence in a deterministic canonical JSONL.GZ file.
   Each line is canonical UTF-8 JSON, ordering is deterministic, and gzip `mtime=0`.
4. Register the file in `hydraulic_task_artifact` with a root-relative storage key,
   SHA-256, byte length, record count, media type, schema version, and publication state.
5. Publish in two durable phases: validate and write result rows plus `prepared`
   metadata, commit, atomically replace the final file, then mark both artifact and
   task published/success. Temporary paths are removed on failure.
6. A successful task is immutable. Unique constraints and the task state gate reject
   duplicate replacement; failed/pre-success attempts may replace their own rows.
7. Downloads resolve only inside `DAYU_STORAGE_ROOT`, require a successful v4 task and
   published artifact, and recheck file size and SHA-256 before returning bytes.

## Failure and compensation boundary

- Validation, serialization, or pre-commit database failure rolls back result rows and
  does not expose the artifact.
- Failure before atomic replace leaves no final file and the task is not successful.
- A crash after the prepared commit but before publication is visible through
  `artifact_status=prepared`; stale recovery requires reconciliation rather than blind
  numerical replay.
- A missing or corrupt published file fails download integrity checks.
- A task already marked `success` cannot be overwritten by ordinary retry or duplicate
  delivery.

## Consequences

The database stays queryable for normal UI series while the complete numerical
evidence remains downloadable and auditable. The design does not provide remote object
storage, retention automation, IAM, or a general crash-reconciliation daemon; these
remain later platform work.

