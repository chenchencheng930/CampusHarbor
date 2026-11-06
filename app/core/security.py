import base64
import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import UserAccount


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return "pbkdf2_sha256$210000$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, hashed: str) -> bool:
    if hashed.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, digest_hex = hashed.split("$", 3)
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
            ).hex()
            return hmac.compare_digest(candidate, digest_hex)
        except (ValueError, TypeError):
            return False
    # Existing installations contain legacy SHA-256 hashes; keep them readable
    # so a deployment can migrate accounts without a forced password reset.
    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, hashed)


def _credentials(request: Request) -> tuple[str, str]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Basic authorization")
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username, password
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Basic authorization") from exc


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> UserAccount:
    username, password = _credentials(request)
    user = db.query(UserAccount).filter(UserAccount.username == username).first()
    if user is None or user.account_status != "ACTIVE" or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")
    return user


def require_admin(user: Annotated[UserAccount, Depends(current_user)]) -> UserAccount:
    if "ROLE_ADMIN" not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def require_verified_admin(user: Annotated[UserAccount, Depends(require_admin)]) -> UserAccount:
    if user.admin_verification_status != "VERIFIED":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "管理员身份尚未认证通过")
    return user


def require_system_admin(user: Annotated[UserAccount, Depends(require_verified_admin)]) -> UserAccount:
    if user.admin_role not in {"SYSTEM_ADMIN", "DEMO_ADMIN"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅系统管理员可以执行此操作")
    return user


def require_risk_admin(user: Annotated[UserAccount, Depends(require_verified_admin)]) -> UserAccount:
    if user.admin_role not in {"COUNSELOR", "ADVISOR", "DEMO_ADMIN"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "系统管理员不能访问心理风险数据")
    return user


def require_counselor(user: Annotated[UserAccount, Depends(require_verified_admin)]) -> UserAccount:
    if user.admin_role not in {"COUNSELOR", "DEMO_ADMIN"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅心理中心老师可以处理风险个案")
    return user
