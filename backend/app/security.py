from datetime import datetime, timedelta
from typing import Optional
import jwt
import bcrypt
from app.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generate a bcrypt hash for a password."""
    # Ограничиваем длину пароля до 72 байт для bcrypt
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    to_encode = {"sub": subject, "iat": datetime.utcnow()}
    expire = datetime.utcnow() + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def decode_token(token: str):
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])

