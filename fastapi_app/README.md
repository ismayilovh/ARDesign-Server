# ARPatent FastAPI backend

3D model conversion service. Upload a ZIP containing an OBJ/STL/STP/IGES/GLB/FBX
file; a Celery worker spawns an ephemeral converter container that produces a GLB
for AR viewing.

Stack: FastAPI + async SQLAlchemy + Alembic + Celery + Redis + Postgres + nginx.

> **Every command in this README assumes you are inside `fastapi_app/`.**
> Start each session with:
> ```bash
> cd fastapi_app
> ```

Dev and prod are isolated by Compose project name:

| Environment | Project name | Volumes (e.g.) |
|---|---|---|
| dev  | `arpatent`       | `arpatent_postgres_data`      |
| prod | `arpatent-prod`  | `arpatent-prod_postgres_data` |

So the two environments have independent databases and media. You can run one,
tear it down, run the other — they don't see each other's data.

---

## Prerequisites

- Docker + Docker Compose v2
- Node 20+ (only for running the dev frontend outside Docker)
- [ngrok](https://ngrok.com/) (for exposing prod publicly — see below)
- The converter image, pulled on the host (worker spawns it as a sibling
  container per conversion — it is not built from this repo):
  ```bash
  docker pull ismayilovh/ardesign-converter:latest
  ```
  Set `CONVERTER_IMAGE` in `.env` to a specific published tag for deployments;
  the default is `ismayilovh/ardesign-converter:latest`.

---

## Development

Uses `docker-compose.yml`. Bind-mounts source for hot reload, runs uvicorn with
`--reload`, credentials hardcoded for local convenience. Frontend runs outside
Docker via Vite so you get instant HMR.

Bring up the backend:
```bash
docker compose up --build
```

In another terminal, run the frontend:
```bash
cd frontend
npm install
npm run dev
```

- API:       http://localhost:8000
- API docs:  http://localhost:8000/docs
- Frontend:  http://localhost:5173 (vite proxies `/api` and `/health` to :8000)
- DB:        reachable only inside the compose network

Tail logs:
```bash
docker compose logs -f api worker
```

Shell in:
```bash
docker compose exec api bash
docker compose exec worker bash
```

Stop:
```bash
docker compose down           # keep volumes (db, media survive)
docker compose down -v        # wipe volumes — dev reset button
```

---

## Production

Uses `docker-compose.prod.yml`. No source bind mount, 4 uvicorn workers, nginx
in front of the api on port 80, image pinned to an explicit tag.

Public access is exposed via **ngrok**, which terminates TLS at its edge and
tunnels plain HTTP to `localhost:80` (nginx). We don't run on a machine with a
public IP, so the `certbot` service and the HTTPS block in `nginx/nginx.conf`
are dormant — see "Public access with a real domain" at the bottom if that
changes.

### First-time setup

All commands run from `fastapi_app/`.

**1. Create `.env`:**
```bash
cp .env.example .env
```
Edit `.env`:
- Set a strong `POSTGRES_PASSWORD`.
- Set a strong `JWT_SECRET_KEY`.
- Leave `CORS_ORIGINS` as the placeholder for now — you'll set it in step 5.
- `APP_VERSION=v0.1.0` (must match the image tag in step 3).
- `MEDIA_VOLUME_NAME=arpatent-prod_media_data` (default in `.env.example`).

`APP_VERSION` is read automatically from `.env` by Compose, so you don't need
to `export` it. Works on Windows cmd/PowerShell, git bash, and Linux.

**2. Pull the converter image:**
```bash
docker pull ismayilovh/ardesign-converter:latest
```
The worker launches this image through the host Docker socket. To roll out a
converter change on an existing deployment, first pull the image, set
`CONVERTER_IMAGE=ismayilovh/ardesign-converter:<tag>` in `.env` (use the exact
tag you published; `latest` is the default), then recreate only the worker:
```bash
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate worker
docker compose -f docker-compose.prod.yml logs -f worker
```
This leaves the API and named data volumes running. The worker briefly restarts;
in-flight conversions may be retried by Celery. To roll back, set
`CONVERTER_IMAGE=youndria/arpatent:1.5` in `.env`, pull that tag if it is still
available, and run the same worker recreation command.

**3. Build the api image** (tag must match `APP_VERSION` in `.env`):
```bash
docker build -t arpatent-api:v0.1.0 .
```

**4. Bring up the stack:**
```bash
docker compose -f docker-compose.prod.yml up -d
```

On first run this builds the React frontend (via the `frontend-builder`
one-shot service, which populates the `frontend_dist` volume and exits), then
starts db, redis, api, worker, socket-proxy, and nginx.

**5. Apply migrations:**
```bash
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Migrations are intentionally a separate step so a failed migration aborts the
release before traffic shifts. See [Migrations](#migrations).

**6. Expose via ngrok** (in another terminal):
```bash
ngrok http 80
```
Copy the `https://...ngrok-free.app` URL ngrok prints — that is the public
address for both the API and the frontend.

**7. Update `CORS_ORIGINS`** in `.env` to match the ngrok URL, then re-apply
just the api so it picks up the new env:
```bash
docker compose -f docker-compose.prod.yml up -d api
```

If the ngrok subdomain changes every restart, use a reserved domain (paid
tier) or `--subdomain=arpatent` so `CORS_ORIGINS` stays stable.

Hit the ngrok URL in a browser. Done.

### Starting the server

After first-time setup, every subsequent start is:
```bash
docker compose -f docker-compose.prod.yml up -d
ngrok http 80
```

Named volumes persist across `down`/`up`, so the DB, migrations, and uploaded
models are already there. If `CORS_ORIGINS` in `.env` still matches the ngrok
URL, nothing else to do.

### Stopping the server

```bash
docker compose -f docker-compose.prod.yml down
```

This stops and removes containers but **keeps the named volumes**
(`arpatent-prod_postgres_data`, `arpatent-prod_media_data`,
`arpatent-prod_frontend_dist`, `arpatent-prod_certbot_*`). DB rows and
uploaded files are intact on the next `up`.

> **Never use `down -v` in prod.** The `-v` flag deletes the volumes, which
> means you lose the Postgres database and every uploaded model. `-v` is a
> dev-only reset button.

To pause without removing containers:
```bash
docker compose -f docker-compose.prod.yml stop
docker compose -f docker-compose.prod.yml start
```

### Deploying a new version

```bash
# 1. Build and tag the new image
docker build -t arpatent-api:v0.2.0 .

# 2. Bump APP_VERSION=v0.2.0 in .env

# 3. Apply any new migrations BEFORE rolling the app
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

# 4. Roll api + worker onto the new image
docker compose -f docker-compose.prod.yml up -d api worker

# 5. If the frontend changed, rebuild it and restart nginx:
docker compose -f docker-compose.prod.yml up -d --build frontend-builder
docker compose -f docker-compose.prod.yml restart nginx
```

Nginx has `depends_on: api: condition: service_healthy` — it waits for
`/health` to pass before routing traffic, so a bad deploy fails visibly
instead of silently 502-ing.

### Rolling back

App-only rollback (no schema change): set `APP_VERSION=v0.1.0` in `.env`, then:
```bash
docker compose -f docker-compose.prod.yml up -d api worker
```

Rollback across a migration: downgrade the DB first, then flip the image.
```bash
docker compose -f docker-compose.prod.yml exec api alembic downgrade -1
# edit .env: APP_VERSION back to the previous version
docker compose -f docker-compose.prod.yml up -d api worker
```

Only safe if the migration has a working `downgrade()` — test it on a staging
DB before you need it for real. Data migrations are often one-way; restore
from `pg_dump` is the fallback.

### Migrating an existing deployment (one-time)

If you previously ran as root, `media_data` contains files owned by UID 0.
The new image runs as UID 1000 (`app`) and cannot write to root-owned dirs.
Fix once, before starting:
```bash
docker compose -f docker-compose.prod.yml run --rm --user root api \
  chown -R 1000:1000 /app/media
```

Skip on fresh installs.

### Admin panel

The app has a role-gated admin panel (manage users, designs, and the Locarno
classification tree). Authorization is a single `role` column on the user
(`USER` / `ADMIN`), checked fresh from the DB on every request — the JWT carries
identity, not privilege, so a stolen normal-user token can't reach `/api/admin/*`
(it gets a 403).

There is **no HTTP route to self-promote** — the first admin is created
out-of-band with a management command against the running `api` container.
Because the command ships inside the image (under `app/scripts/`, not the
dockerignored top-level `scripts/`), it runs identically in dev and prod:

```bash
# prod
docker compose -f docker-compose.prod.yml exec api python -m app.scripts.set_admin <username>

# dev
docker compose exec api python -m app.scripts.set_admin <username>
```

The user must already exist (register through the UI first), and must re-login
afterward for the new role to appear in their session. After the first admin
exists, all further role changes go through the panel
(`PATCH /api/admin/users/{id}`). To demote, add `--revoke`. The command refuses
to demote/remove the last remaining admin.

> The command is just a thin wrapper over a DB write the `api` container can
> already make — it is not an additional attack surface. The real escalation
> levers are keeping `JWT_SECRET_KEY` secret (a leaked secret lets an attacker
> mint an admin token) and preventing code execution inside the container.

### Public access with a real domain (optional)

If you move off ngrok to a server with a public IP and your own domain:

1. Uncomment the HTTPS server block in `nginx/nginx.conf` and replace
   `yourdomain.com` with your domain.
2. Get a certificate via the built-in certbot service:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm certbot certonly \
     --webroot -w /var/www/certbot -d yourdomain.com --agree-tos -m you@example.com
   ```
3. Reload nginx:
   ```bash
   docker compose -f docker-compose.prod.yml restart nginx
   ```
4. Set `CORS_ORIGINS=https://yourdomain.com` in `.env`, then
   `up -d api`.

Renewals: `docker compose -f docker-compose.prod.yml run --rm certbot renew`
on a cron. This whole path is untested in production from this repo — treat
it as a starting point, not a recipe.

---

## Migrations

Alembic lives under `fastapi_app/alembic/`. Migrations run as a deliberate
step, not automatically on container start — a failed migration aborts the
release before traffic shifts.

All commands below assume `cd fastapi_app`.

### Create a new migration

After editing `app/models/*.py`:

**Dev:**
```bash
docker compose exec api alembic revision --autogenerate -m "short description"
```

Review the generated file under `alembic/versions/`. Autogenerate misses:

- Column renames (it drops + adds — data loss)
- Check constraints
- Enum value additions (for Postgres — you must write
  `op.execute("ALTER TYPE ... ADD VALUE ...")` by hand)
- Data backfills

Edit the migration to fix any of these before committing.

### Apply migrations

**Dev:**
```bash
docker compose exec api alembic upgrade head
```

**Prod** — one-shot container before deploying the new app version:
```bash
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

`run --rm` starts a disposable container with the same image and env, runs
the command, and exits. It does not touch the running `api` / `worker`.

### Inspect state

```bash
docker compose exec api alembic current        # current revision
docker compose exec api alembic history        # all revisions
docker compose exec api alembic heads          # tip(s) of the graph
```

(For prod, swap `exec api` for `-f docker-compose.prod.yml exec api`.)

### Downgrade

```bash
docker compose exec api alembic downgrade -1           # one step back
docker compose exec api alembic downgrade <revision>   # to a specific revision
docker compose exec api alembic downgrade base         # wipe all migrations
```

### Rules

- Never edit a migration already applied anywhere. Add a new one.
- Keep schema changes and data migrations in separate revision files — lets
  you roll back schema independently of data.
- Write migrations to be compatible with both the old and new app code: add a
  column in one release, start reading it in the next, drop the old column in
  a third. This is the only way a rollback across a deploy is non-destructive.
- If you've never run `alembic downgrade` on a migration, you don't have
  rollback for it — you have hope.
