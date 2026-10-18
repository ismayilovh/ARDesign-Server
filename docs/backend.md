# Backend overview

The backend is a FastAPI application backed by PostgreSQL. Celery workers handle conversion and other long-running jobs through Redis, keeping HTTP request handling responsive. The browser frontend and AR clients use the API to manage designs and retrieve model media.

## Responsibilities

- **Ingestion and conversion:** accept model archives, validate their contents, and produce a GLB suitable for AR viewing.
- **Design management:** associate submissions with their owners, metadata, and Locarno classification.
- **Review and moderation:** manage submission review and expose approved designs through public catalog and media routes.
- **Serving:** provide authenticated or public access to designs and media according to ownership, review state, and media-token rules.
- **Administration:** manage users, designs, and classification data through role-gated routes.

The current repository also contains image-generation integration points in its worker and API code. Availability depends on the configured generator service and deployment environment.

## Technology stack

| Concern | Technology |
|---|---|
| HTTP API | FastAPI, Uvicorn / Gunicorn |
| Database | PostgreSQL, SQLAlchemy async API and synchronous worker sessions |
| Migrations | Alembic |
| Background jobs | Celery and Redis |
| Frontend | React and Vite |
| Packaging and deployment | Docker, Docker Compose, nginx in production |
| Upload validation | MIME sniffing, image validation, ZIP structure and size checks |

Authorization uses the `UserRole` model. Admin and expert access should follow the current role gates in `app.api.deps`; consult the generated [route reference](api/routes.md) and [user model](api/models.md) as roles evolve.

## Upload path

The model-upload endpoint accepts a ZIP containing a supported model file. Validation happens before work is queued. A Celery task invokes the configured external converter container, stores its output, and schedules thumbnail generation. See [Workflows](flows.md) for the lifecycle and [Deployment](deployment.md) for the converter image configuration.
