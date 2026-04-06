# ADR-0003: Python Stack Choice

## Status

Accepted

## Date

2026-03-25

## Context

The challenge allows free choice of language and framework, but requires the choice to be
argued. Three realistic candidates were evaluated: Python (FastAPI + Strawberry), Go
(standard library or gin/chi + gqlgen), and TypeScript (Node.js + NestJS + type-graphql).

## Decision

Use **Python 3.12** with **FastAPI**, **Strawberry GraphQL**, and **SQLAlchemy 2.0 async**.

## Rationale

### Primary reason: production Python experience enables meaningful review

The single most important factor: this solution will be code-reviewed by engineers who can
assess whether architectural decisions are genuinely sound or just structurally correct on
the surface. Production Python experience means every decision — the ordering of invariant
checks in `consume()`, the choice of Redis pipeline atomicity for session creation, the
deliberate rejection of hard account lockout — can be critically evaluated, not just accepted
at face value. Writing the same architecture in Go or TypeScript would produce code that
looks correct but cannot be validated at the engineering depth this challenge is assessing.

### Secondary reasons

**Strawberry (code-first GraphQL) composes naturally with DDD**

Strawberry uses Python dataclasses as GraphQL types. Domain value objects, entity fields,
and DTOs map directly to schema types without a separate `.graphql` schema file to keep in
sync. The `@strawberry.type` decorator adds schema metadata to existing Python classes —
the domain model drives the schema, not the reverse.

**Async SQLAlchemy 2.0 is production-mature**

The 2.0 API eliminates implicit I/O (all I/O is explicit `await`) and aligns with Python's
async model. The `async_sessionmaker` pattern integrates cleanly with FastAPI's dependency
injection. No ORM magic leaks into the domain layer because repositories own the
ORM↔entity mapping boundary.

**FastAPI lifespan + async ecosystem**

FastAPI's `lifespan` context manager initialises the Redis connection pool and DB engine
once at startup, and tears them down on shutdown. Middleware (SlowAPI rate limiting),
dependency injection (`Depends`), and Strawberry's `context_getter` all compose on the
same ASGI stack without impedance mismatch.

**pytest-asyncio + httpx for testing**

The async test stack (`pytest-asyncio`, `httpx.AsyncClient`) tests the full stack
end-to-end with minimal boilerplate. Integration tests run against a real test database
(`auth_test`) and real Redis — no mock/prod divergence risk for critical auth paths.

## Alternatives considered

### Go (gqlgen + pgx + go-redis)

Pros: higher throughput, smaller memory footprint, strong concurrency model, gqlgen
generates type-safe resolver scaffolding.

Cons: the primary reason above applies — Go expertise is lower, so subtle architectural
mistakes would not be caught during review. gqlgen's schema-first approach requires
maintaining a `.graphql` file in sync with Go types, adding a translation layer between
the domain model and the schema. The domain model in Go would be structurally correct but
the invariant placement decisions could not be validated with the same confidence.

### TypeScript (NestJS + type-graphql)

Pros: code-first GraphQL (type-graphql uses decorators like Strawberry), strong ecosystem,
NestJS has built-in DI and module system.

Cons: same primary reason applies. Additionally, NestJS's opinionated module/provider/
decorator system tends to blur DDD layer boundaries — it is easy to accidentally couple
domain logic to the framework's lifecycle or decorator metadata. Async SQLAlchemy has no
direct TypeScript equivalent; TypeORM and Prisma both have different trade-offs.

## Consequences

- Python's raw throughput is lower than Go or Node.js. For an auth service where the
  bottleneck is Redis and Postgres I/O (not CPU), this is not a limiting factor at the
  scale targeted by the challenge.
- Python's GIL limits true parallelism per process. Mitigated by running multiple uvicorn
  workers (or using gunicorn + uvicorn workers) behind a load balancer — standard production
  deployment for FastAPI services.
- Python's type system is structural and optional. `mypy` (or pyright) can enforce type
  correctness statically; the current implementation uses type annotations throughout and
  can be checked with `mypy auth_service/ --strict` as a future CI step.
