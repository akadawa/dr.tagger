---
description: Workflow for local Docker development and optional push to docker.io
---

# Docker Development Workflow

This workflow describes how to manage the `drtagger` project exclusively via Docker.

## Local Development
1.  **Build and Start**: Use `docker-compose -f local-compose.yml up --build -d` for local testing.
2.  **Clean Rebuild**: Use `docker-compose -f local-compose.yml down --rmi all && docker-compose -f local-compose.yml up --build -d`.
3.  **Logs**: Use `docker logs -f drtagger`.

## Docker.io (Docker Hub) Policy
Wait for user confirmation before pushing any images to `docker.io`. We use semantic versioning (e.g., `v1.0.0`).

### Pushing to Docker Hub
1.  **Ask User**: "Soll das neue Image (Version <vX.Y.Z>) nach docker.io gepusht werden?"
2.  **Tag Image**: `docker tag drtagger:latest akadawa/drtagger:<version>`
3.  **Push**: `docker push akadawa/drtagger:<version>`
4.  **Latest Tag**: `docker tag drtagger:latest akadawa/drtagger:latest && docker push akadawa/drtagger:latest`
