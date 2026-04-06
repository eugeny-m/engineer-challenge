# ADR-0001: GraphQL over gRPC / REST

## Status

Accepted

## Date

2026-03-25

## Context

The challenge explicitly prefers gRPC and/or GraphQL over plain REST for the API layer.
Beyond the challenge requirements, the auth service has a natural command/query split
(CQRS) that needs a clean API representation, and clients may be browser-based (limiting
raw gRPC options without a proxy).

Three options were evaluated:

1. REST (JSON over HTTP/1.1)
2. gRPC (Protocol Buffers over HTTP/2)
3. GraphQL (schema-first or code-first over HTTP/1.1)

## Decision

Use **GraphQL via Strawberry** (code-first, Python).

## Rationale

### Why not REST

- REST does not have a structural concept of "mutation vs query" — you impose CQRS
  conventions by hand (POST for commands, GET for queries) with no enforcement.
- Versioning and schema evolution require URL versioning or content negotiation, adding
  operational overhead for what is effectively a stable, bounded-context API.
- The challenge explicitly downweights pure REST without strong architectural justification.

### Why not gRPC

- Browser clients cannot call gRPC directly without a transcoding proxy (gRPC-Web,
  grpc-gateway, or Envoy). For an auth service that is often the first integration point
  for web clients, this adds infrastructure complexity.
- Python gRPC tooling (grpcio, betterproto) has more boilerplate than Strawberry.
- The introspection and Playground developer experience of GraphQL is significantly better
  for a challenge where reviewers need to explore the API.

### Why GraphQL

- The CQRS split maps directly onto GraphQL's `Mutation` (command side) and `Query`
  (query side) types — no conventions needed, the schema enforces the split structurally.
- Strawberry is code-first: Python dataclasses become GraphQL types automatically. DDD
  value objects and domain entities compose cleanly into the schema without a separate
  schema definition file to keep in sync.
- Strawberry integrates natively with FastAPI (ASGI), sharing the same async event loop
  and lifespan context — Redis and DB connections are initialised once and reused.
- GraphQL introspection and the built-in Playground at `/graphql` make the service
  immediately explorable for reviewers without a Postman collection.
- Single endpoint simplifies rate limiting configuration: all mutations flow through
  `/graphql`, and the custom ASGI middleware inspects GraphQL operation names to apply per-operation limits.

## Consequences

- All clients must speak HTTP/1.1 with JSON — no binary encoding benefit from gRPC.
- N+1 query risk exists in GraphQL (mitigated: the service's query surface is small and
  does not expose list resolvers that would trigger N+1 patterns).
- GraphQL errors are returned with HTTP 200 by default. The implementation uses custom
  error extensions to include error codes, preserving semantic clarity for clients.
- If an internal microservice (non-browser) caller needs maximum throughput, adding a gRPC
  endpoint in a future iteration is straightforward — command handlers are transport-agnostic.
