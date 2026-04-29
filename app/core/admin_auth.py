import os
from datetime import datetime
from typing import Dict, List

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_admin_token, hash_password
from app.models.entities import AdminUser

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "super_admin": [
        "orders:read",
        "orders:confirm",
        "inventory:read",
        "inventory:write",
        "admins:manage",
        "support:read",
        "support:reply",
        "support:close",
    ],
    "manager": [
        "orders:read",
        "orders:confirm",
        "inventory:read",
        "inventory:write",
        "support:read",
        "support:reply",
        "support:close",
    ],
    "support": [
        "orders:read",
        "inventory:read",
        "support:read",
        "support:reply",
    ],
}

ROLE_NAMES = {
    "super_admin": "超级管理员",
    "manager": "运营管理员",
    "support": "客服只读",
}


def normalize_role(role: str) -> str:
    role = (role or "support").strip()
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail="角色必须是 super_admin / manager / support")
    return role


def seed_first_admin(db: Session) -> None:
    exists = db.query(AdminUser).first()
    if exists:
        return

    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "123456")

    admin = AdminUser(
        username=username,
        password_hash=hash_password(password),
        role="super_admin",
        is_active=1,
        created_at=datetime.utcnow(),
    )
    db.add(admin)
    db.commit()


def get_current_admin(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> AdminUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后台")

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_admin_token(token)
    admin_id = payload.get("sub")

    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()

    if not admin or int(admin.is_active or 0) != 1:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员不存在或已被禁用")

    return admin


def get_admin_from_token(token: str, db: Session) -> AdminUser:
    payload = decode_admin_token(token)
    admin_id = payload.get("sub")

    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()

    if not admin or int(admin.is_active or 0) != 1:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员不存在或已被禁用")

    return admin


def require_permission(permission: str):
    def checker(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
        perms = ROLE_PERMISSIONS.get(admin.role, [])
        if permission not in perms:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前管理员权限不足")
        return admin

    return checker


def admin_to_dict(admin: AdminUser):
    return {
        "id": admin.id,
        "username": admin.username,
        "role": admin.role,
        "role_name": ROLE_NAMES.get(admin.role, admin.role),
        "permissions": ROLE_PERMISSIONS.get(admin.role, []),
        "is_active": bool(admin.is_active),
        "created_at": str(admin.created_at) if admin.created_at else None,
        "last_login_at": str(admin.last_login_at) if admin.last_login_at else None,
    }
