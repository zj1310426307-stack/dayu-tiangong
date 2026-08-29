# ADR-HYDRO-D2-RC1-0004: Result and Artifact Reconciliation

- Status: accepted for the RC1 candidate implementation
- Date: 2026-08-28

## Context

Native-v4 output spans relational result rows and a local evidence file. PostgreSQL
and an atomic filesystem rename cannot participate in one transaction, so crashes can
leave a durable prepared database state without a final file, or a final file without
the final database publication CAS. Blind numerical replay could then overwrite valid
prepared evidence or hide an integrity incident.

## Decision

1. Publication remains a bounded three-step protocol:

   1. validate the scientific result, write/fsync a temporary file, and atomically
      rename it to a token-SHA-256/content-SHA-256-bound attempt staging path; replace
      the task's result rows, insert Artifact metadata as `prepared` (including the
      staging identity), update the task to `artifact_status=prepared`, and commit
      using the active execution token;
   2. acquire the task and Artifact row locks, revalidate token, metadata, size and
      SHA-256, then atomically promote the attempt staging file to the deterministic
      canonical path;
   3. while those locks remain held, CAS the task to `success/published` and the
      Artifact row from `prepared` or `publishing` to `published` in the same database
      transaction.

2. A stale attempt in `persisting`, `publishing_artifact`, or `finalizing`, or with a
   finalization Artifact state, is marked `reconciliation_required`. It cannot be
   manually retried until reconciliation produces a clean state.
3. Reconciliation is restricted to one native-v4 task, the exact canonical key
   `hydraulic-evidence/task-{task_id}-stage-evidence-v1.jsonl.gz`, and the one attempt
   staging key that can be recomputed from trusted row metadata. It resolves both
   under `DAYU_STORAGE_ROOT`, inspects only exact non-symlink temporary siblings, and
   moves rejected files only into `hydraulic-evidence/quarantine` under that same root.
4. The operator command is read-only by default:

   ```text
   python -m app.model_engine.reconcile_v4_task --task-id 123
   python -m app.model_engine.reconcile_v4_task --task-id 123 --apply
   ```

   The first command returns a JSON dry-run report. Only explicit `--apply` locks rows
   and performs the bounded action.
5. The reconciler refuses active `running`/`cancel_requested` tasks or any task with an
   active token. Stale recovery or cancellation completion must run first.
6. Prepared evidence can be promoted only when metadata, size/hash, result schema and
   path, prepared diagnostics, non-cancelled terminal state, and required Section/Gate/
   Pump rows are all present. Reconciliation never turns a scientific failure into a
   success merely because a file exists.
7. A stale attempt staging file is never promoted by reconciliation, even when its
   hash is correct. It is quarantined because its lease no longer authorizes canonical
   publication. Only a canonical file already produced before a crash may complete
   the prepared scientific publication checks.

## Deterministic Cases A-F

| Case | Observed state | Dry-run outcome | `--apply` action |
|---|---|---|---|
| Case A | No Artifact metadata and no final file | `clean_no_artifact` | For a failed/cancelled task, normalize task Artifact state to `none`; no file action |
| Case B | `prepared` metadata; no temporary or final file | `prepared_artifact_missing` | Mark Artifact row and task Artifact state `failed`; a terminal task may then pass the normal retry gate |
| Case C | Prepared metadata; final file exists and size/SHA-256 match | `publishable_prepared_artifact` when the prepared scientific result is complete | Complete task/Artifact publication and record reconciliation provenance |
| Case D | Prepared metadata; final file exists but size or SHA-256 differs | `artifact_integrity_mismatch` | Quarantine the file and mark Artifact integrity failed; never promote the task |
| Case E | Task is `success`, metadata is `published`, but final file is missing | `published_artifact_missing` | Mark task/Artifact integrity failed so normal result and download APIs reject it; record an operational incident |
| Case F | Final file exists with no Artifact metadata | `orphan_final_file` | Quarantine the orphan; use `none` for a non-success task or `failed` for a success integrity incident |

Orphan attempt staging/temporary files are also quarantined. Invalid metadata paths are failed without
inspecting that path. Cancelled-task files and files not backed by a complete prepared
scientific result are quarantined and are never published.

## Consequences

The local backend has deterministic, operator-controlled recovery for the known
attempt-stage/canonical-promote/final-CAS gaps. The design does not scan arbitrary storage, repair
remote object stores, automatically replay numerical work, or provide a general
distributed recovery coordinator.

This ADR does not claim that fault-injection tests, hosted services, or RC1 release
gates have passed.
