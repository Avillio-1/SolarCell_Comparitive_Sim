# Architecture Overview

SolarClean-DT is a Python modular monolith. The package is split into domain, application, infrastructure, CLI, and configuration layers.

## Dependency Direction

```text
solarclean.cli
  -> solarclean.application
    -> solarclean.domain
      <- solarclean.infrastructure
```

Domain code owns the stable language of the simulator:

- canonical weather datasets;
- clean energy profiles;
- contamination and soiling states;
- farm and cohort state;
- simulation events and daily baseline results.

Infrastructure code owns replaceable external details:

- NASA POWER HTTP and cache behavior;
- CSV weather import;
- deterministic fixture weather;
- pvlib PVWatts calculations;
- output writing and plotting.

The current phase intentionally excludes web frameworks, databases, drone/CV logic, coating state, economics, optimization, and cloud deployment.
