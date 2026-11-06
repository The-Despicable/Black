# ADR 0001 — Deployment Strategy: Native-Only

## Status
Accepted

## Context
The Raphael RedTeam repository was migrating from a Docker-based microservices architecture (v2) to a native Python deployment (v3 Black Hat Harness). Audit findings revealed inconsistency: `pyproject.toml` and README claim zero Docker, but `configs/docker-compose.yml` remains as a first-class artifact with 18+ services.

## Decision
Commit to **native-only deployment**. Remove all Docker Compose files and Dockerfiles from the active codebase. Move legacy Docker artifacts to `legacy/deployment/` with a clear deprecation notice.

## Rationale
- Simplifies packaging and reduces attack surface
- Eliminates dependency on Docker daemon
- Aligns with pyproject.toml package scope (harness*, cloak_service*)
- Reduces maintenance burden of dual deployment paths

## Consequences
- Legacy v2 services (cai-service, mhddos-service, etc.) are no longer deployable via Docker
- Users must install Python dependencies directly
- Docker Compose file preserved in legacy/ for reference only

## Related
- ADR 0002: Governance Unification
- pyproject.toml: package scope narrowed to harness* and cloak_service*
