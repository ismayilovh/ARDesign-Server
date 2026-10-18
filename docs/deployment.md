# Deployment

The Compose files under `fastapi_app/` describe development and production environments. The full, current operational instructions—including environment setup, upgrades, rollback, migrations, and volume handling—are maintained in [`fastapi_app/README.md`](https://github.com/ismayilovh/ARDesign-Server/blob/master/fastapi_app/README.md).

## Services

| Service | Purpose |
|---|---|
| `db` | PostgreSQL application database |
| `redis` | Celery broker and result backend |
| `api` | FastAPI application |
| `worker` | Celery conversion and thumbnail tasks |
| `socket-proxy` | Restricts Docker API access for containerized workers |
| `nginx` | Production reverse proxy and frontend hosting |
| `frontend-builder` | Builds the React frontend into the shared production volume |
| `certbot` | Optional certificate renewal service for domain deployments |

The converter image is pulled separately and selected through `CONVERTER_IMAGE`. Pin a version for deployments rather than relying on a moving tag.

## Development quickstart

From `fastapi_app/`:

```bash
docker compose up --build
docker compose exec api alembic upgrade head
```

The API listens on `http://localhost:8000`; interactive API docs are at `http://localhost:8000/docs`. For the frontend, run `npm install` and `npm run dev` in `fastapi_app/frontend/`.

## Production checklist

1. Create `.env` from `.env.example` and set strong secrets and public origins.
2. Pull the configured converter image and build or select the API image version.
3. Start the production Compose stack.
4. Apply Alembic migrations as an explicit release step.
5. Configure public ingress, TLS, and the correct CORS origins.
6. Back up the database and persistent media before upgrades.

Never remove production volumes as part of routine shutdown. See the README’s migration and rollback sections before changing schema or image versions.
