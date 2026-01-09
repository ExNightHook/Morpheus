from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt

from app.config import settings
from app.database import get_db
from app.models import AdminUser
from app.security import verify_password

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/login")


def authenticate_admin(username: str, password: str, db: Session) -> AdminUser | None:
    admin = db.query(AdminUser).filter_by(username=username).first()
    if admin and verify_password(password, admin.password_hash):
        return admin
    return None


def get_current_admin(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> AdminUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    admin = db.query(AdminUser).filter_by(username=username).first()
    if admin is None:
        raise credentials_exception
    return admin

