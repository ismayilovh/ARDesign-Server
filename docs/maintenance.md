# Maintenance notes

These notes capture architectural constraints visible in the current implementation. Verify behavior against the source before changing it; the generated [API reference](api/routes.md) is built from the checked-out code.

## Keep HTTP handlers and background work separate

Long-running model conversion belongs in Celery tasks. API routes should persist state and enqueue work rather than blocking while a converter runs.

## Keep database session styles in their context

FastAPI routes use asynchronous database sessions. Worker tasks use synchronous sessions. Use the matching session factory for each execution context.

## Preserve converter isolation

The worker launches an external converter container and transfers input and output explicitly. Review the worker task’s Docker security options before changing container networking, mounts, capabilities, or resource limits.

## Treat uploaded files as untrusted

ZIP entries, model files, and images are user-controlled. Keep archive traversal, symlink, size, compression-ratio, file-count, MIME, and image decoding protections aligned with the accepted formats.

## Keep migrations deliberate

Do not edit migrations that have already been applied. Review generated Alembic revisions for renames, constraints, enum changes, and data migrations; test both upgrade and downgrade behavior where rollback is required. The deployment README documents the migration workflow.

## Respect role and review gates

Routes should use the shared authorization dependencies and review-state rules. Avoid duplicating access checks in frontend-only logic; authorization must be enforced server-side.

## Avoid process-local caches for shared mutable data

The application runs across multiple API and worker processes. A cache local to one process cannot reliably reflect edits made by another process unless there is an explicit invalidation strategy.
