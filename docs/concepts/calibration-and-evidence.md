# Calibration and evidence

SolarClean-DT separates study values from evidence and uncertainty ranges.

## Two sources

| Source | Role |
| --- | --- |
| Project configuration | Central values used by one run |
| `data/calibration/parameter_registry.yaml` | Units, low/central/high ranges, sources, confidence, status, and limitations |

The canonical configuration selects `riyadh_central_v2`. The registry does not override all YAML
values during a normal run; robustness studies apply supported registry ranges to validated
configuration fields or economic inputs.

## Evidence labels

| Field | Values |
| --- | --- |
| `evidence_type` | measured, literature, quoted, calculated, inferred, assumed |
| `confidence` | high, medium, low |
| `status` | validated, provisional, blocked, unsourced |

`measured` describes direct observations from the target or a documented comparable site.
`provisional` means the value can support research and sensitivity work but not an unqualified
field decision. `blocked` means a required source or interface is absent.

## Interpreting the Riyadh set

Near-Riyadh and Saudi literature anchors the soiling envelope, seasonal direction, and rainfall
threshold ranges. These are not measurements from the target farm. Bird behavior, selected
inspection performance, field coating costs, logistics, and several economic inputs remain weaker.

The external PVDAQ holdouts test whether the simulation framework can reproduce daily production
and soiling/rain dynamics at comparable sites. They do not validate Riyadh parameter values.

## Using ranges

Use one-way sensitivity to identify influential parameters, joint maps to find interactions, and
Monte Carlo to estimate modeled ranking stability. Do not narrow a range because a preferred
scenario loses, and do not treat a stable result as evidence that omitted mechanisms are
unimportant.

See [assumptions and limitations](../validation/assumptions-and-limitations.md) and
[evidence sources](../validation/evidence-sources.md).
