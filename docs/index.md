# ARDesign Server

ARDesign Server is the web backend for the ARDesign platform. It manages user accounts and design submissions, converts uploaded 3D models, supports image-based model generation, coordinates expert review, and serves approved designs and model media to clients.

The service is built with FastAPI, PostgreSQL, SQLAlchemy, Alembic, Celery, and Redis. Docker Compose runs the API and background workers alongside the database, broker, and supporting services.

## Documentation

| Guide | Contents |
|---|---|
| [Overview](backend.md) | Responsibilities, capabilities, and technology stack |
| [Architecture](architecture.md) | Services, code layers, and data model |
| [Workflows](flows.md) | Upload, conversion, image generation, and review lifecycles |
| [Deployment](deployment.md) | Development and production deployment summary |
| [Maintenance](maintenance.md) | Design decisions that matter when changing the backend |
| [API reference](api/routes.md) | Routes and generated Python API details |

## Run locally

The complete operational guide is [`fastapi_app/README.md`](https://github.com/ismayilovh/ARDesign-Server/blob/master/fastapi_app/README.md). In brief:

```bash
cd fastapi_app
docker compose up --build
```

The API is available at `http://localhost:8000`; interactive OpenAPI documentation is at `/docs`. Run the React development frontend separately from `fastapi_app/frontend/`.
