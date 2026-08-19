# HYDRO-MODEL-01 gate-pump demo

This deterministic software-acceptance case contains one 5 km river, 20
sections, a gate at chainage 2.5 km, an external-outflow pump at 4 km, a
constant upstream discharge and a constant downstream level. It runs for 24
hours and records hourly results.

Run from the repository root:

```powershell
backend\.venv\Scripts\python.exe examples/hydraulic/gate-pump-demo/run_demo.py
```

`input.json` is a frozen `dayu.model-input.v3` snapshot with three contiguous
HydraulicReach records, matching top-level/nested structure envelopes, and four
frozen water-level rules. The gate is bound to Reach 102 at 2.5 km. The pump
withdraws at node `N-4000`, with its 4 km chainage explicitly identified as a
synthetic demo contract rather than inferred production data.

`result_summary.json` is a concise,
reproducible output checked by `tests/test_gate_pump_simulation.py`; the script
does not overwrite either committed file.

Scientific boundary: this example exercises the existing
`synchronous-network-continuity-manning-v1` quasi-steady network router. It is
not an unsteady Saint-Venant calibration case and must not be used for an
engineering dispatch decision.

## Browser visual-acceptance fixture

When the complete PostgreSQL/Celery API stack is unavailable, the dispatch run
detail page can be inspected against a deliberately narrow, read-only fixture:

```powershell
backend\.venv\Scripts\python.exe examples/hydraulic/gate-pump-demo/serve_ui_fixture.py
$env:VITE_BACKEND_TARGET='http://127.0.0.1:8019'
npm --prefix frontend run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/dispatch/runs/1?datasetVersionId=1`. The fixture
runs `HydraulicEngine` twice at startup (baseline and controlled), then maps
the live results to the existing generated client's read endpoints. The
provenance and exact sample hours are available from `/fixture/evidence`.

This proves only that the UI renders real engine output. It does **not** prove
the PostgreSQL persistence, backend route implementation, Celery workflow, or
full API/database closure.
