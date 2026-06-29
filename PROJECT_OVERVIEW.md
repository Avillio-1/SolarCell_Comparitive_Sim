# SolarClean-DT Project Overview

SolarClean-DT is a modular Python digital-twin foundation for a 10,000-panel photovoltaic farm in Saudi Arabia.

The completed Phase 1-3 system provides:

- provider-independent hourly weather ingestion;
- NASA POWER, CSV, and deterministic fixture weather adapters;
- clean PV production using pvlib PVWatts;
- no-intervention baseline soiling with rainfall cleaning;
- representative-panel and cohort-based farm representations;
- CLI commands, CSV/JSON/YAML outputs, diagnostic plots, tests, and architecture documentation.

Phase 3.5 extends the foundation with validation, reproducibility, and reporting infrastructure. It must not add Phase 4 scenario behavior such as drones, computer vision, manual cleaning, coatings, economics, sensitivity analysis, APIs, or dashboards.
