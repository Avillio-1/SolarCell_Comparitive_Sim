# ADR-001: Modular Monolith

## Status

Accepted.

## Decision

Build SolarClean-DT as a Python modular monolith with clean domain, application, infrastructure, CLI, and configuration layers.

## Rationale

Phases 1-3 require local simulation, reproducibility, and clear scientific boundaries. Microservices, databases, web frameworks, and cloud deployment would add operational complexity without helping the current acceptance criteria.

## Consequences

The code can run locally from a fresh Python installation. Future web or batch interfaces can call the same application use cases without changing domain code.
