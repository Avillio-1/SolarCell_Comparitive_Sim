# High-Level Architecture Diagram

This is the primary map of SolarClean-DT. Solid arrows show runtime calls or data movement;
dashed arrows show adapter-to-contract relationships.

```mermaid
flowchart TB
    USER["Users / automation"]

    subgraph PRESENTATION["Presentation and entry points"]
        CLI["solarclean.cli.main<br/>Typer CLI"]
        WEB["solarclean.dashboard.app<br/>FastAPI + Jinja dashboard"]
        JOBS["solarclean.dashboard.jobs<br/>background job registry"]
        WEB --> JOBS
    end

    subgraph APPLICATION["Application orchestration — solarclean.application"]
        RUNS["use_cases + phase35<br/>weather, clean PV, individual scenarios, validation"]
        T6["comparison.CompareAllScenarios<br/>simulate, reconcile, rank, recommend"]
        T7["monte_carlo + sensitivity<br/>uncertainty, sweeps, winner maps, break-even"]
        T7 -->|"reuses comparison as a black box"| T6
    end

    subgraph DOMAIN["Domain — solarclean.domain"]
        CONTRACTS["environment.weather + pv.model + scenario.contracts<br/>provider-independent inputs, strategy protocol, results"]
        EVENTS["events + random<br/>immutable exogenous event tape and deterministic RNG streams"]
        ENGINE["simulation.scenario_engine<br/>single shared annual daily loop"]
        STRATEGIES["baseline_strategy + reactive_cv + coating<br/>MitigationStrategy implementations"]
        PHYSICS["contamination + farm<br/>soiling, rainfall response, cohort state"]
        ECON["economics + calibration<br/>economic engine and parameter registry"]
        VALIDATION["validation<br/>scientific validation report contracts"]

        ENGINE --> CONTRACTS
        ENGINE --> EVENTS
        STRATEGIES -.->|"implement MitigationStrategy"| CONTRACTS
        STRATEGIES --> PHYSICS
        STRATEGIES --> EVENTS
        ECON --> CONTRACTS
        VALIDATION --> CONTRACTS
    end

    subgraph INFRASTRUCTURE["Infrastructure adapters — solarclean.infrastructure"]
        WEATHER["weather<br/>NASA POWER, CSV, fixture, cache"]
        PVLIB["pvlib_adapter.pvwatts<br/>clean PV calculation"]
        PERSIST["persistence<br/>CSV, JSON, reports, plots"]
    end

    subgraph CONFIGURATION["Validated configuration — solarclean.config"]
        CFG["loader + Pydantic models"]
    end

    subgraph EXTERNAL["External systems and data"]
        YAML["configs/*.yaml"]
        REGISTRY["data/calibration/parameter_registry.yaml"]
        NASA["NASA POWER API"]
        LOCAL["Measured CSV / deterministic fixtures"]
        OUTPUTS["outputs/run-id<br/>artifact packages"]
    end

    USER --> CLI
    USER --> WEB

    CLI --> CFG
    CLI --> RUNS
    CLI --> T6
    CLI --> T7
    WEB --> CFG
    JOBS --> T6
    JOBS --> T7

    CFG --> RUNS
    CFG --> T6
    CFG --> T7

    RUNS --> ENGINE
    RUNS --> STRATEGIES
    RUNS --> EVENTS
    RUNS --> VALIDATION
    RUNS --> WEATHER
    RUNS --> PVLIB
    RUNS --> PERSIST

    T6 --> ENGINE
    T6 --> STRATEGIES
    T6 --> EVENTS
    T6 --> ECON
    T6 --> WEATHER
    T6 --> PVLIB
    T6 --> PERSIST
    T7 --> PERSIST

    WEATHER -.->|"implements WeatherProvider; returns WeatherDataset"| CONTRACTS
    PVLIB -.->|"implements PVPowerModel; returns CleanEnergyProfile"| CONTRACTS
    PERSIST -.->|"serializes domain results"| CONTRACTS

    YAML --> CFG
    REGISTRY --> ECON
    WEATHER --> NASA
    WEATHER --> LOCAL
    PERSIST --> OUTPUTS
    OUTPUTS -->|"read and display artifacts"| WEB
```

The domain owns simulation rules and contracts. Network access, pvlib objects, plotting, and
filesystem writes remain in infrastructure; the CLI and dashboard invoke application use cases.
