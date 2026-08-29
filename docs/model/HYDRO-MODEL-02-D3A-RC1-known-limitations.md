# HYDRO-MODEL-02-D3A-RC1 Known Limitations

D3A-RC1 仅支持：single Branch、fully wet、forward、`Fr<=0.8`、正 section-effective Manning、显式下降床高、连续渐变非同 tabulated Profiles、一个 completed-interface Gate 和一个 external Q-H/Q-efficiency Pump；用途为 synthetic validation only。

以下能力明确不支持：

- Junction、multi-Branch、loop/network；
- wetting/drying、rewetting、reverse、supercritical、transcritical、hydraulic jump、dam-break；
- internal Pump、多 Gate、多 Pump、variable-speed Pump；
- lateral compound roughness、突变断面、bridge、culvert、weir、floodplain zoning；
- sediment、2D、HEC-RAS/MIKE11 runtime integration；
- 真实工程率定、预测、MPC/GA 优化、PLC/SCADA 和生产水决策。

运行状态即使 finite、CFL 和水量通过，只要 depth/Q/Fr 离开 runtime envelope，任务仍 fail closed。RC1 FINAL 收敛是合成物理问题，不代表真实河道率定或现场可用性。
