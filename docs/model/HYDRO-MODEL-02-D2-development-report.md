# HYDRO-MODEL-02-D2 Development Report

## Release baseline

- Main protection was enabled before D1 merge and retains strict PR/check rules.
- D1 PR #10 merge commit: `cc6936d9d48d64c46a78ba85bed77c473e20cff3`.
- Annotated D1 tag: `hydro-model-02-d1-rc1`, target `cc6936d`.
- D2 base: `cc6936d`; branch: `feature/HYDRO-MODEL-02-D2-v4-task-platform`.

## Delivered chain

```text
SimulationCase → readiness/preview → frozen dayu.model-input.v4
→ solver registry → hydraulic-v4-d1 Worker → D1 v4-lite-7 runtime
→ dayu.hydraulic-result.v3 → authoritative rows + stage artifact
→ FastAPI/OpenAPI → task monitor and Gate/Pump result UI
```

The implementation also adds diagnostic v3/v4 shadow grouping with independent
snapshots, solvers, results, and bounded common-coordinate deltas.

## Commit sequence

```text
97e4870 audit(d2): freeze v4 platform baseline
ffff8bb feat(d2): add solver registry and native v4 contract
a0ce1eb feat(d2): add native v4 persistence schema
ee442e6 feat(d2): add readiness and snapshot freeze
16d90cc feat(d2): add native v4 worker lifecycle
329aa45 feat(d2): add result v3 persistence and evidence artifacts
3206588 feat(d2): add diagnostic v3 v4 shadow grouping
ab22939 feat(d2): add v4 API and generated OpenAPI client
b8ee7c3 feat(d2): add Gate Pump task and result UI
5ab3788 ci(d2): add native v4 platform gates
bc8d3a1 test(d2): close hosted platform task chain
9060223 fix(d2): isolate hosted integration identities
```

The final documentation commit is listed by the PR history.

## Compatibility and scope

v1/v2/v3 behavior and legacy result tables were retained. Callback plumbing is
observational and does not change the D1 result when absent. No D1 scientific expected
value was modified. All v4 unsupported scope fails closed before task creation or
execution.

## Operational boundary

The D2 API remains for internal deployment. It does not fabricate IAM, accept a
client-declared trusted actor, or expose local paths. Production auth, remote object
storage, multi-tenant isolation, and general crash reconciliation remain NO-GO.
