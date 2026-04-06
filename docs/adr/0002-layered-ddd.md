# ADR-0002: Layered DDD over Hexagonal Architecture

## Status

Accepted

## Date

2026-03-25

## Context

DDD implementations commonly use one of two structural patterns for organising the
relationship between domain logic and infrastructure:

1. **Layered architecture** — domain → application → infrastructure, with strict
   downward dependency rules (inner layers know nothing about outer layers).
2. **Hexagonal architecture (ports and adapters)** — explicit primary ports (driving,
   e.g. HTTP handlers) and secondary ports (driven, e.g. repositories), with adapters
   on each side. The application core is surrounded by a port boundary on all sides.

## Decision

Use **layered DDD** (domain / application / infrastructure / presentation).

## Rationale

### Hexagonal adds ceremony not justified at this scope

The canonical hexagonal structure requires:
- Explicit primary port interfaces (e.g., `IRegisterUserUseCase`) implemented by handlers
- Explicit secondary port interfaces (e.g., `IUserRepository`) implemented by adapters
- Adapter packages on both sides of the application core

For three user flows and six command handlers, defining primary port interfaces (use-case
interfaces that the presentation layer calls through) is pure ceremony — there is exactly
one implementation of each use case and no test doubles that implement the primary ports.
The secondary ports (repository and service interfaces) are already present in
`application/ports/` — that is the genuinely valuable part of hexagonal, and it is retained.

### Layered DDD achieves the same dependency inversion

The actual engineering goal of hexagonal is that the domain and application layers have
zero compile-time or import-time dependency on infrastructure. The layered structure
achieves this:

- `domain/` imports nothing outside the standard library.
- `application/` imports `domain/` and declares port interfaces. No imports from
  `infrastructure/` or `presentation/`.
- `infrastructure/` imports `application/ports/` and `domain/`. Never imported by
  `application/` or `domain/`.
- `presentation/` imports `application/` handlers and DTOs. Does not import
  infrastructure directly (it receives implementations through dependency injection
  via `container.py`).

The dependency inversion is complete. All infrastructure can be swapped by replacing
implementations in `container.py` without touching any other layer.

### Testability

Unit tests mock the secondary ports (repository interfaces, hasher, token service, email
service) — the same approach that hexagonal uses. Primary port interfaces would add a
layer of indirection without improving test isolation.

## Consequences

- The structure is immediately recognisable to engineers familiar with Clean Architecture,
  Onion Architecture, or standard DDD layering — lower onboarding cost than strict hexagonal.
- If the service grows to the point where multiple implementations of primary ports are
  needed (e.g., a CLI adapter and an HTTP adapter both calling the same use-case interface),
  primary port interfaces can be introduced incrementally without restructuring the existing code.
- The `container.py` dependency injection wiring is explicit and visible — no magic framework
  scanning. This is intentional: DI frameworks (e.g. Dependency Injector) would be appropriate
  for a larger service but add indirection here for marginal benefit.
