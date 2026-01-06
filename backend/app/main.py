import asyncio
import logging
import secrets
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import Base, engine, SessionLocal
from app.models import AdminUser
from app.security import get_password_hash
from app.routers import admin, public, payments
from app.services.bot import run_bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("morpheus")

app = FastAPI(title="Morpheus Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(public.router)
app.include_router(payments.router)


@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    ensure_admin()
    asyncio.create_task(run_bot())
    logger.info("Startup complete")


def ensure_admin():
    with SessionLocal() as db:
        admin = db.query(AdminUser).first()
        if not admin:
            username = "admin"
            password = secrets.token_hex(8)
            admin = AdminUser(username=username, password_hash=get_password_hash(password))
            db.add(admin)
            db.commit()
            logger.info("Generated admin credentials - username: %s password: %s", username, password)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/Morpheus Private/")
def panel_entry():
    return RedirectResponse(url="/docs")

