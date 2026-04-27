from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.admin_auth import require_permission
from app.models.entities import AdminUser

router = APIRouter(prefix="/inventory", tags=["inventory"])


class AddInventoryRequest(BaseModel):
    product_code: str
    codes: Any


def _get_inventory_table(db: Session) -> Dict[str, Any]:
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()

    table_name = None
    for name in ["inventory", "inventory_items", "inventory_item"]:
        if name in tables:
            table_name = name
            break

    if not table_name:
        raise HTTPException(status_code=500, detail="找不到库存表：inventory / inventory_items")

    cols = {c["name"] for c in inspector.get_columns(table_name)}

    product_col = "product_code" if "product_code" in cols else "product"
    content_col = "item_value" if "item_value" in cols else ("content" if "content" in cols else "code")

    if product_col not in cols:
        raise HTTPException(status_code=500, detail="库存表缺少 product_code 或 product 字段")

    if content_col not in cols:
        raise HTTPException(status_code=500, detail="库存表缺少 item_value、content 或 code 字段")

    return {
        "table": table_name,
        "cols": cols,
        "product_col": product_col,
        "content_col": content_col,
        "status_col": "status" if "status" in cols else None,
        "used_col": "is_used" if "is_used" in cols else None,
    }


def _available_where(meta: Dict[str, Any]) -> str:
    parts = []

    if meta["status_col"]:
        parts.append("LOWER(COALESCE(status, 'available')) IN ('available', 'new', 'unused')")

    if meta["used_col"]:
        parts.append("(is_used = false OR is_used IS NULL)")

    if not parts:
        return "1=1"

    return "(" + " OR ".join(parts) + ")"


@router.get("/stats")
def inventory_stats(db: Session = Depends(get_db)):
    meta = _get_inventory_table(db)
    table = meta["table"]
    product_col = meta["product_col"]
    available_where = _available_where(meta)

    sql = text(f"""
        SELECT
            {product_col} AS product_code,
            COUNT(*) AS total,
            SUM(CASE WHEN {available_where} THEN 1 ELSE 0 END) AS available,
            SUM(CASE WHEN NOT ({available_where}) THEN 1 ELSE 0 END) AS used
        FROM {table}
        GROUP BY {product_col}
        ORDER BY {product_col}
    """)

    rows = db.execute(sql).mappings().all()

    products = ["GPT", "CLAUDE", "VIP", "MJ"]
    result = {p: {"product_code": p, "total": 0, "available": 0, "used": 0} for p in products}

    for r in rows:
        p = str(r["product_code"] or "").upper()
        result[p] = {
            "product_code": p,
            "total": int(r["total"] or 0),
            "available": int(r["available"] or 0),
            "used": int(r["used"] or 0),
        }

    return {"items": list(result.values())}


@router.get("/list")
def inventory_list(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("inventory:read")),
):

    meta = _get_inventory_table(db)
    table = meta["table"]
    product_col = meta["product_col"]
    content_col = meta["content_col"]
    available_where = _available_where(meta)

    sql = text(f"""
        SELECT
            id,
            {product_col} AS product_code,
            {content_col} AS content,
            CASE WHEN {available_where} THEN 'available' ELSE 'used' END AS status
        FROM {table}
        ORDER BY id DESC
        LIMIT 300
    """)

    rows = db.execute(sql).mappings().all()

    return {
        "items": [
            {
                "id": r["id"],
                "product_code": r["product_code"],
                "content": r["content"],
                "status": r["status"],
            }
            for r in rows
        ]
    }


@router.post("/add")
def add_inventory(
    payload: AddInventoryRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("inventory:write")),
):

    meta = _get_inventory_table(db)
    table = meta["table"]
    cols = meta["cols"]
    product_col = meta["product_col"]
    content_col = meta["content_col"]

    if isinstance(payload.codes, str):
        codes = [x.strip() for x in payload.codes.splitlines() if x.strip()]
    elif isinstance(payload.codes, list):
        codes = [str(x).strip() for x in payload.codes if str(x).strip()]
    else:
        raise HTTPException(status_code=400, detail="codes 必须是一行一个卡密的文本或数组")

    if not codes:
        raise HTTPException(status_code=400, detail="没有可添加的卡密")

    inserted = 0

    for code in codes:
        fields = [product_col, content_col]
        values = [":product_code", ":content"]

        params = {
            "product_code": payload.product_code.upper(),
            "content": code,
        }

        if "status" in cols:
            fields.append("status")
            values.append(":status")
            params["status"] = "available"

        if "is_used" in cols:
            fields.append("is_used")
            values.append(":is_used")
            params["is_used"] = False

        if "item_type" in cols:
            fields.append("item_type")
            values.append(":item_type")
            params["item_type"] = "redeem_code"

        if "created_at" in cols:
            fields.append("created_at")
            values.append(":created_at")
            params["created_at"] = datetime.utcnow()

        sql = text(f"""
            INSERT INTO {table} ({", ".join(fields)})
            VALUES ({", ".join(values)})
        """)

        db.execute(sql, params)
        inserted += 1

    db.commit()

    return {
        "ok": True,
        "msg": "库存添加成功",
        "product_code": payload.product_code.upper(),
        "inserted": inserted,
    }
