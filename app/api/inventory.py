from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy import inspect, text, bindparam
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.admin_auth import require_permission
from app.models.entities import AdminUser

router = APIRouter(prefix="/inventory", tags=["inventory"])


class AddInventoryRequest(BaseModel):
    product_code: str
    codes: Any


def _ensure_inventory_logs_table(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS inventory_logs (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER,
            admin_name VARCHAR(80),
            action VARCHAR(50),
            product_code VARCHAR(100),
            quantity INTEGER,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))


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
        parts.append("(is_used = false OR is_used IS NULL OR is_used = 0)")

    if not parts:
        return "1=1"

    return "(" + " OR ".join(parts) + ")"


def _write_inventory_log(
    db: Session,
    admin: AdminUser,
    action: str,
    product_code: str,
    quantity: int,
    detail: str,
):
    _ensure_inventory_logs_table(db)

    db.execute(text("""
        INSERT INTO inventory_logs
        (admin_id, admin_name, action, product_code, quantity, detail, created_at)
        VALUES
        (:admin_id, :admin_name, :action, :product_code, :quantity, :detail, :created_at)
    """), {
        "admin_id": admin.id,
        "admin_name": admin.username,
        "action": action,
        "product_code": product_code,
        "quantity": quantity,
        "detail": detail,
        "created_at": datetime.utcnow(),
    })


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

    products = [
        "GPT", "CLAUDE", "VIP", "MJ",
        "GPT_SHARED_1M", "GPT_PLUS_1M", "GPT_PLUS_3M", "GPT_TEAM_1M",
        "CLAUDE_SHARED_1M", "CLAUDE_PRO_1M", "CLAUDE_PRO_3M",
        "MJ_BASIC_1M", "MJ_STANDARD_1M", "MJ_PRO_1M",
        "GEMINI_PRO_1M", "PERPLEXITY_PRO_1M", "CURSOR_PRO_1M",
        "AI_BUNDLE_1M",
    ]

    result = {
        p: {"product_code": p, "total": 0, "available": 0, "used": 0}
        for p in products
    }

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
    product_code = payload.product_code.upper()

    for code in codes:
        fields = [product_col, content_col]
        values = [":product_code", ":content"]

        params = {
            "product_code": product_code,
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

    _write_inventory_log(
        db=db,
        admin=current_admin,
        action="add",
        product_code=product_code,
        quantity=inserted,
        detail=f"新增库存 {inserted} 条",
    )

    db.commit()

    return {
        "ok": True,
        "msg": "库存添加成功",
        "product_code": product_code,
        "inserted": inserted,
    }


@router.post("/delete")
def delete_inventory(
    ids: List[int] = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("inventory:write")),
):
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的库存")

    ids = list({int(x) for x in ids if int(x) > 0})

    if not ids:
        raise HTTPException(status_code=400, detail="请选择有效库存 ID")

    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="单次最多删除 100 条库存")

    meta = _get_inventory_table(db)
    table = meta["table"]
    product_col = meta["product_col"]
    content_col = meta["content_col"]

    select_sql = text(f"""
        SELECT id, {product_col} AS product_code, {content_col} AS content
        FROM {table}
        WHERE id IN :ids
    """).bindparams(bindparam("ids", expanding=True))

    rows = db.execute(select_sql, {"ids": ids}).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="没有找到要删除的库存")

    product_codes = {str(r["product_code"] or "").upper() for r in rows}
    product_code = list(product_codes)[0] if len(product_codes) == 1 else "MULTI"

    delete_sql = text(f"""
        DELETE FROM {table}
        WHERE id IN :ids
    """).bindparams(bindparam("ids", expanding=True))

    db.execute(delete_sql, {"ids": [r["id"] for r in rows]})

    preview = []
    for r in rows[:10]:
        preview.append(f"ID={r['id']} / {r['product_code']} / {str(r['content'])[:80]}")

    detail = "删除库存：\n" + "\n".join(preview)
    if len(rows) > 10:
        detail += f"\n... 还有 {len(rows) - 10} 条"

    _write_inventory_log(
        db=db,
        admin=current_admin,
        action="delete",
        product_code=product_code,
        quantity=len(rows),
        detail=detail,
    )

    db.commit()

    return {
        "ok": True,
        "msg": "库存删除成功",
        "deleted": len(rows),
    }


@router.get("/logs")
def inventory_logs(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("inventory:read")),
):
    _ensure_inventory_logs_table(db)
    db.commit()

    rows = db.execute(text("""
        SELECT
            id,
            admin_id,
            admin_name,
            action,
            product_code,
            quantity,
            detail,
            created_at
        FROM inventory_logs
        ORDER BY id DESC
        LIMIT 200
    """)).mappings().all()

    return {
        "items": [
            {
                "id": r["id"],
                "admin_id": r["admin_id"],
                "admin_name": r["admin_name"],
                "action": r["action"],
                "product_code": r["product_code"],
                "quantity": r["quantity"],
                "detail": r["detail"],
                "created_at": str(r["created_at"]) if r["created_at"] else None,
            }
            for r in rows
        ]
    }
