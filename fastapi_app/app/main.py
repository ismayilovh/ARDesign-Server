from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, locarno, patents
from app.api.routes import admin, expert
from app.core.config import settings

app = FastAPI(title="ARDesign API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patents.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(locarno.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(expert.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
