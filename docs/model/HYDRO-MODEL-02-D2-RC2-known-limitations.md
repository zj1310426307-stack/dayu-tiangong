# HYDRO-MODEL-02-D2-RC2 Known Limitations

RC2 closes build identity and bounded queued-message recovery only. The candidate
remains:

- validation-only and not calibrated;
- not approved for production water decisions;
- without public IAM/RBAC or multi-tenancy;
- without remote object-store high availability;
- without distributed database/file/broker transactions;
- without multi-version Worker routing;
- limited to the frozen D1 scientific scope: a single Branch, fully wet,
  forward-subcritical flow, one completed-interface Gate, and one external Pump;
- without a general river network, wet/dry fronts, reverse flow, or internal Pump.

An OCI revision and solver build ID improve provenance but do not constitute image
signing, supply-chain attestation, disaster recovery, engineering calibration, or
production availability certification.
