# ADR-0001: Modular monolith

## Status

Accepted.

## Context

The simulator needs stable scientific contracts while weather sources, persistence, and user
interfaces can change independently. Distributed deployment is not required.

## Decision

Keep one Python package divided into domain, application, infrastructure, configuration, and
interface layers. Dependencies point toward domain contracts. External services, pvlib objects,
files, plots, CLI parsing, and dashboard behavior stay outside the domain.

## Consequences

The architecture can be tested offline and deployed as one process. Boundary discipline is
required; splitting services would add coordination without current benefit.
