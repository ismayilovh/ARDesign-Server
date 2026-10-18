# ARDesign Server

FastAPI backend for the ARDesign platform, with PostgreSQL persistence, Celery background workers, Redis, and a React frontend.

- **Documentation:** [ARDesign Server docs](https://ismayilovh.github.io/ARDesign-Server/)
- **Local development and production runbook:** [fastapi_app/README.md](fastapi_app/README.md)
- **API schema:** run the service and visit `http://localhost:8000/docs`

To start the development stack:

```bash
cd fastapi_app
docker compose up --build
```

See the [documentation overview](docs/index.md) for architecture, workflows, deployment guidance, maintenance notes, and the generated API reference.
