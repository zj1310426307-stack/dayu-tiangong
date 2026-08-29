# HYDRO-MODEL-02-D2-RC2 Build Identity Baseline Audit

- Date: 2026-08-28
- Base SHA: `a9c2152e2f21f2963c54247a95c2fe659116a962`
- Branch: `feature/HYDRO-MODEL-02-D2-v4-task-platform`
- PR: #11, OPEN / NOT MERGED
- Decision before implementation: **P0 OPEN / RC2 NO-GO**

## Current identity sources

1. Generic task creation imports `ENGINE_VERSION` from
   `backend/app/model_engine/provenance.py`, where the product string is copied as a
   module constant. Dispatch and Optimization import that same backend constant, while
   native-v4 candidate construction independently defaults another environment key.
2. `simulation_task.engine_commit` is read from `ENGINE_COMMIT` at task-creation time.
   Generic, Dispatch, Optimization, and native-v4 paths each contain their own fallback;
   the fallbacks include `uncommitted`.
3. Compose services independently declare the same Dockerfile under `build`. They are
   source-equivalent but are not bound to one immutable image tag or verified image ID,
   so Backend, legacy Worker, v4 Worker, and scheduler are not guaranteed to be the same
   build artifact.
4. Compose currently defines `ENGINE_COMMIT=${ENGINE_COMMIT:-local-compose}`, which can
   persist a mutable human label as if it were task provenance.
5. The Hosted workflows do not inject `${{ github.sha }}` into the model runtime. Their
   current tasks can therefore use the development fallback even when CI itself is tied
   to a Git commit.
6. The v4 Worker revalidates the five-field Registry route, source snapshot, projection,
   mesh, solver policy, validation policy, and Registry hash. Neither Worker compares the
   task's engine commit/build identity with the build that is actually executing it.
7. A task frozen under build A can remain queued and then be claimed by build B when the
   registered route is unchanged. The row keeps build A text, while build B silently
   performs the computation.
8. `docker/backend.Dockerfile` has no build identity arguments and no OCI revision,
   version, or source labels.
9. The shipping backend image uses Python 3.12. Existing Backend, Worker, fault, D1, and
   MODEL02 Hosted jobs use Python 3.11; they do not execute the shipping image.
10. Queued recovery selects only `queue_job_id IS NULL` plus stale `queued_time`.
    `queue_job_id` proves that publication once returned an ID, not that Redis still owns
    the message, so a lost message with a non-null marker is suppressed forever.

## Root cause

Task provenance is creation-side text, not a verified runtime contract. Code identity,
Registry identity, container identity, and queue-delivery liveness are recorded by
separate owners with no single fail-closed comparison boundary.

## RC2 closure design

- Add pure `model/build_identity.py` as the only owner of engine version, commit
  validation, build mode, Registry-bound deterministic solver build ID, and diagnostic
  serialization.
- Freeze the resulting identity on every newly created v1-v4 SimulationTask and in
  native-v4 source/result/artifact provenance.
- Compare the frozen task identity with the executing legacy/v4 Worker identity after
  claim and before solver invocation; mismatch fails with
  `D2_RUNTIME_BUILD_MISMATCH` and never rewrites the task.
- Add migration `20260828_0022` for build identity and bounded delivery telemetry without
  fabricating verified identity for historical rows.
- Treat `queue_job_id` as a historical publish marker. Recover any unclaimed queued task
  after the delivery timeout, throttle with `last_delivery_time`, and fail closed at the
  documented maximum delivery attempts.
- Build one shared backend image for Backend/Workers/scheduler, inject an immutable SHA,
  add OCI labels, and execute a Python 3.12 shipping-runtime E2E in Hosted CI before the
  new exact check is added to main protection.

## Frozen boundary

This audit authorizes no new hydraulic physics, production IAM, multi-version Worker
routing, remote object-store HA, distributed transaction, merge, or tag. D1 numerical
events and balances remain the release regression authority.
