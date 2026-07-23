# Documentation

Use the page that matches the question you are trying to answer. The canonical configuration for
examples is `configs/offline_fixture_full_year.yaml`.

## Getting started

- [Install and run the first comparison](getting-started/first-run.md)

## Guides

- [Run and interpret a comparison](guides/run-a-comparison.md)
- [Use fixture, NASA POWER, or measured CSV weather](guides/use-weather-data.md)
- [Validate against measured production](guides/validate-field-data.md)
- [Run the dashboard](guides/use-dashboard.md)
- [Contribute safely](guides/contributing.md)

## Reference

- [Configuration](reference/configuration.md)
- [CLI commands](reference/cli.md)
- [Output files](reference/outputs.md)
- [Weather data contract](reference/weather.md)
- [Scenario contracts](reference/scenario-contracts.md)

## Concepts

- [Architecture](concepts/architecture.md)
- [Simulation model](concepts/simulation-model.md)
- [Scenario comparability](concepts/scenario-comparability.md)
- [Calibration and evidence](concepts/calibration-and-evidence.md)

## Validation

- [Validation method](validation/method.md)
- [Field-validation results](validation/field-results.md)
- [Assumptions and limitations](validation/assumptions-and-limitations.md)
- [Reproduce validation](validation/reproducibility.md)
- [Evidence sources](validation/evidence-sources.md)

## Architecture decision records

ADRs record only decisions that constrain multiple parts of the system. See the
[ADR index](adr/README.md).

## Documentation rules

- Keep one purpose per page.
- Put procedures in guides, exact contracts in reference, and rationale in concepts or ADRs.
- Link to one canonical explanation instead of repeating it.
- Label synthetic data, assumptions, and measured evidence explicitly.
- Prefer commands that can be copied from the repository root.
