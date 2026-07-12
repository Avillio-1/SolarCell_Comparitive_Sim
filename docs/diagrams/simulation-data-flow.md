# Simulation Data-Flow Diagram

This diagram follows the canonical `compare-all-scenarios` run. The central fan-out is deliberate:
baseline, reactive, and coating all receive the same copy-protected weather snapshot and the same
immutable environmental event tape.

```mermaid
flowchart TD
    ENTRY["CLI compare-all-scenarios<br/>or dashboard job"] --> CFG["load_config()<br/>validated SolarCleanConfig"]
    CFG --> RUN["CompareAllScenarios.run()"]
    RUN --> VALIDATE["validate configuration<br/>and calibration registry"]

    subgraph SHARED["Shared inputs — each resolved exactly once per comparison run"]
        REQUEST["build WeatherRequest"] --> PROVIDER["selected WeatherProvider.load()"]
        PROVIDER --> WEATHER["one WeatherDataset<br/>canonical hourly weather"]
        WEATHER --> PVMODEL["PVWattsPowerModel.calculate_hourly()"]
        PVMODEL --> CLEAN["one CleanEnergyProfile<br/>hourly + daily clean energy"]

        CLEAN --> DATES["simulation dates"]
        CFG --> TAPE_GEN["generate_event_tape()<br/>deterministic RNG streams"]
        DATES --> TAPE_GEN
        TAPE_GEN --> TAPE["one ExogenousEventTape<br/>frozen event tuple + read-only mappings"]

        WEATHER --> CONTEXT["ONE ScenarioContext<br/>FrozenWeatherInput: deep copy, copy-on-read<br/>FrozenCleanEnergyInput: deep copy, copy-on-read<br/>same ExogenousEventTape + read-only metadata"]
        CLEAN --> CONTEXT
        TAPE --> CONTEXT
        CFG -->|"farm configuration + input checksums"| CONTEXT
    end

    VALIDATE --> REQUEST

    DAILY_LOOP["Shared daily-loop algorithm in every engine run<br/>weather → DailyEnvironment<br/>clean profile → daily clean energy<br/>event tape → DailyEventInputs<br/>then DailyScenarioInput → strategy.simulate_day()"]

    subgraph SCENARIOS["Same engine class, weather snapshot, and event tape; different MitigationStrategy"]
        BASE["ScenarioSimulationEngine.run()<br/>BaselineStrategy"]
        REACTIVE["ScenarioSimulationEngine.run()<br/>ReactiveCVStrategy"]
        COATING["ScenarioSimulationEngine.run()<br/>CoatingStrategy"]
    end

    CONTEXT -->|"same context object"| BASE
    CONTEXT -->|"same context object"| REACTIVE
    CONTEXT -->|"same context object"| COATING
    DAILY_LOOP -.->|"identical loop"| BASE
    DAILY_LOOP -.->|"identical loop"| REACTIVE
    DAILY_LOOP -.->|"identical loop"| COATING

    BASE --> BASE_RESULT["AnnualScenarioResult: baseline<br/>daily results, events, operations"]
    REACTIVE --> REACTIVE_RESULT["AnnualScenarioResult: reactive<br/>daily results, events, operations"]
    COATING --> COATING_RESULT["AnnualScenarioResult: coating<br/>daily results, events, operations"]

    BASE_RESULT --> ECON["aggregate operational quantities<br/>and evaluate annual economics"]
    REACTIVE_RESULT --> ECON
    COATING_RESULT --> ECON
    REGISTRY["ParameterRegistry<br/>calibrated economic inputs"] --> ECON

    WEATHER --> WEATHER_HASH["one weather checksum"]
    TAPE --> TAPE_HASH["one event-tape checksum"]
    ECON --> RECONCILE["build_reconciliation_report()"]
    WEATHER_HASH -->|"assigned to every scenario"| RECONCILE
    TAPE_HASH -->|"assigned to every scenario"| RECONCILE
    RECONCILE --> GATE{"all reconciliation checks pass?"}
    GATE -->|"yes"| RANK["rank scenarios<br/>and build recommendation"]
    GATE -->|"no"| WITHHOLD["withhold ranking<br/>retain failure report"]
    RANK --> RESULT["ComparisonResult"]
    WITHHOLD --> RESULT

    RESULT --> WRITE["write comparison package"]
    WEATHER --> WRITE
    CLEAN --> WRITE
    TAPE --> WRITE
    WRITE --> ARTIFACTS["CSV + JSON + PNG artifacts<br/>shared inputs, scenario summaries, events,<br/>economics, reconciliation, ranking, recommendation"]
    ARTIFACTS --> CONSUMERS["CLI summary / dashboard / downstream analysis"]
```

Scenario strategies consume `DailyEventInputs`; they do not generate or mutate the shared event
tape. Scenario-local random draws may support intervention behavior, but they do not replace or
regenerate the exogenous conditions used for comparison.
