# HYDRO-MODEL-02-D2 API and Frontend Report

## Additive API surface

- SimulationCase v4 readiness and bounded preview;
- generic task create/status/enqueue/cancel/retry/snapshot with native-v4 discrimination;
- v4 Section options and one-Section H/Q/V series;
- v4 Gate, Pump, event, summary/provenance, artifact manifest, and verified download;
- diagnostic v3/v4 shadow-pair create and comparison.

Legacy v1/v2/v3 routes and response shapes remain in place. HTTP handlers perform
validation/error mapping and delegate freezing, execution, results, artifacts, and
shadow logic to services.

The artifact endpoint accepts no path from the client, resolves only database-owned
root-relative keys, and checks task ownership, published state, size, and SHA-256.
These endpoints inherit the current internal-deployment boundary; D2 does not claim
public-production IAM.

## OpenAPI

FastAPI is the source of truth. `npm run openapi:update` validates every required path
and regenerates `frontend/src/api/generated/client.ts`. The hosted `Frontend OpenAPI`
job starts the backend, regenerates the client, enforces zero Git drift, then runs
TypeScript typecheck and production build.

## Frontend

The model workspace offers `Legacy v3` and `Saint-Venant D1 v4（受限）`. Selecting v4
loads readiness, displays solver/capability and fixed scientific limitations, requires a
frozen DispatchPlan, and disables task creation when not ready.

Monitoring shows schema, solver, capability, execution mode/phase, lifecycle state,
progress, simulation time, CFL, accepted steps, categorized retries, heartbeat, and last
event, with cooperative cancel support.

The result workspace loads normal output-interval data only: selectable Section H/Q/V,
Gate series/table, Pump state/operating point/power/energy, event timeline, water balance,
provenance/hash diagnostics, limitations, and artifact link. Full stage evidence is
download-only and is never loaded into ordinary charts.

