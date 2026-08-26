# Gate/Pump strong-coupling example

This frozen HYDRO-MODEL-02-D1 case contains one Branch, 20 prismatic sections,
one completed-interface Gate at CS08/CS09, and one Q-H/Q-efficiency external
Pump at CS16. It runs a six-hour positive inflow hydrograph against an explicit
wet downstream stage process.

Run from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe examples/hydraulic/gate-pump-strong-coupling/case.py
```

The printed summary includes the accepted Gate/Pump event order, water-balance
error, external Pump volume, and accepted-stage Pump input energy. The complete
input is returned by `build_case()`; running the module does not write files.
