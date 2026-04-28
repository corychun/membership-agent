import traceback
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.admin_auth import admin_to_dict, normalize_role, require_permission
from app.core.db import get_db
from app.core.security import create_admin_token, hash_password, verify_password
from app.models.entities import AdminUser, Order
from app.services.delivery import mark_paid_and_deliver

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ConfirmPaidRequest(BaseModel):
    order_no: str


class BulkConfirmPaidRequest(BaseModel):
    order_nos: list[str]


class CreateAdminRequest(BaseModel):
    username: str
    password: str
    role: str = "support"


class UpdateAdminRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


def norm(value):
    return str(value or "").lower()


def is_delivered(order: Order) -> bool:
    return norm(order.delivery_status) in {"delivered", "completed", "success", "sent"}


def can_manual_confirm(order: Order) -> bool:
    if is_delivered(order):
        return False
    return norm(order.payment_status) in {
        "waiting", "pending", "pending_payment", "unpaid", "paid", "finished", "confirmed", "", "none",
    }


def order_to_dict(o: Order):
    return {
        "id": o.id,
        "order_no": o.order_no,
        "product_code": o.product_code,
        "customer_email": o.customer_email,
        "payment_status": o.payment_status,
        "status": o.status,
        "delivery_status": o.delivery_status,
        "delivery_content": o.delivery_content,
        "created_at": str(o.created_at) if o.created_at else None,
        "can_confirm": can_manual_confirm(o),
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = (payload.username or "").strip()
    admin = db.query(AdminUser).filter(AdminUser.username == username).first()

    if not admin or int(admin.is_active or 0) != 1 or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    admin.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(admin)

    token = create_admin_token({"sub": admin.id, "username": admin.username, "role": admin.role})
    return {"ok": True, "access_token": token, "token_type": "bearer", "admin": admin_to_dict(admin)}


@router.get("/me")
def me(current_admin: AdminUser = Depends(require_permission("orders:read"))):
    return {"ok": True, "admin": admin_to_dict(current_admin)}


@router.get("/orders")
def list_orders(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    orders = db.query(Order).order_by(Order.id.desc()).limit(200).all()
    return {"items": [order_to_dict(o) for o in orders]}


@router.post("/orders/confirm-paid")
def confirm_paid_and_deliver(
    payload: ConfirmPaidRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = db.query(Order).filter(Order.order_no == payload.order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if is_delivered(order):
        return {"ok": True, "msg": "already delivered", "order_no": order.order_no, "delivery_content": order.delivery_content}

    if not can_manual_confirm(order):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态不允许发货：payment_status={order.payment_status}, delivery_status={order.delivery_status}",
        )

    try:
        result = mark_paid_and_deliver(db, order)
        db.refresh(order)
        return {"ok": True, "msg": "paid + delivered", "order_no": order.order_no, "delivery_content": order.delivery_content, "result": result}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print("confirm_paid_and_deliver error:")
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"发货失败：{str(e)}")


@router.post("/orders/confirm-paid-bulk")
def confirm_paid_and_deliver_bulk(
    payload: BulkConfirmPaidRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order_nos = []
    seen = set()
    for order_no in payload.order_nos or []:
        value = (order_no or "").strip()
        if value and value not in seen:
            seen.add(value)
            order_nos.append(value)

    if not order_nos:
        raise HTTPException(status_code=400, detail="请选择要确认的订单")
    if len(order_nos) > 50:
        raise HTTPException(status_code=400, detail="单次最多批量处理 50 个订单")

    results = []
    success_count = 0
    failed_count = 0

    for order_no in order_nos:
        order = db.query(Order).filter(Order.order_no == order_no).first()
        if not order:
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": "订单不存在"})
            continue

        if is_delivered(order):
            success_count += 1
            results.append({"order_no": order_no, "ok": True, "msg": "已发货，跳过", "delivery_content": order.delivery_content})
            continue

        if not can_manual_confirm(order):
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": f"状态不允许：payment_status={order.payment_status}, delivery_status={order.delivery_status}"})
            continue

        try:
            result = mark_paid_and_deliver(db, order)
            db.refresh(order)
            success_count += 1
            results.append({"order_no": order_no, "ok": True, "msg": "paid + delivered", "delivery_content": order.delivery_content, "result": result})
        except Exception as e:
            db.rollback()
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": str(e)})

    return {"ok": failed_count == 0, "success_count": success_count, "failed_count": failed_count, "items": results}


@router.get("/admins")
def list_admins(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admins:manage")),
):
    admins = db.query(AdminUser).order_by(AdminUser.id.asc()).all()
    return {"items": [admin_to_dict(a) for a in admins]}


@router.post("/admins")
def create_admin(
    payload: CreateAdminRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admins:manage")),
):
    username = (payload.username or "").strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="管理员账号至少 3 位")
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        raise HTTPException(status_code=400, detail="管理员账号已存在")

    admin = AdminUser(
        username=username,
        password_hash=hash_password(payload.password),
        role=normalize_role(payload.role),
        is_active=1,
        created_at=datetime.utcnow(),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return {"ok": True, "admin": admin_to_dict(admin)}


@router.put("/admins/{admin_id}")
def update_admin(
    admin_id: int,
    payload: UpdateAdminRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admins:manage")),
):
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="管理员不存在")

    if admin.id == current_admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员")

    if payload.password:
        admin.password_hash = hash_password(payload.password)
    if payload.role is not None:
        admin.role = normalize_role(payload.role)
    if payload.is_active is not None:
        admin.is_active = 1 if payload.is_active else 0

    db.commit()
    db.refresh(admin)
    return {"ok": True, "admin": admin_to_dict(admin)}


===== app/static/admin.html =====
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>后台管理</title>
<style>
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:#f6f7fb;margin:0;padding:28px 16px;color:#111827}.wrap{max-width:1320px;margin:auto}.panel{background:#fff;padding:20px;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.06);margin-bottom:18px}button,input,select,textarea{padding:10px 12px;border-radius:9px;font-size:14px;box-sizing:border-box}input,select,textarea{border:1px solid #d1d5db;background:#fff}button{border:none;background:#111827;color:#fff;font-weight:800;cursor:pointer;white-space:nowrap}button.secondary{background:#374151}button.light{background:#eef2ff;color:#3730a3}button.dangerBtn{background:#b91c1c}button.okBtn{background:#047857}button:disabled{background:#9ca3af;color:#fff;cursor:not-allowed}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.muted{color:#6b7280;font-size:13px}.hide{display:none}.pill{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card{background:#f9fafb;border:1px solid #e5e7eb;border-radius:13px;padding:14px}.row2{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:10px}.ok{color:#047857;font-weight:800}.warn{color:#b45309;font-weight:800}.danger{color:#b91c1c;font-weight:800}.blue{color:#3730a3;font-weight:800}textarea{width:100%;min-height:110px;margin-top:10px}table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border-radius:14px;overflow:hidden}th,td{padding:12px;border-bottom:1px solid #e5e7eb;font-size:14px;text-align:left;vertical-align:top}th{background:#f3f4f6;position:sticky;top:0;z-index:1}.tableWrap{max-height:640px;overflow:auto;border:1px solid #e5e7eb;border-radius:14px}.pendingRow{background:#fff7ed}.paidRow{background:#fffbeb}.deliveredRow{background:#f0fdf4}.selectedRow{outline:2px solid #6366f1;outline-offset:-2px}.copyBtn{padding:6px 8px;font-size:12px;background:#eef2ff;color:#3730a3}.smallBtn{padding:7px 9px;font-size:12px}.stats{display:flex;gap:10px;flex-wrap:wrap}.stat{padding:10px 12px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px}.switch{display:flex;gap:8px;align-items:center}.switch input{width:auto}.topBar{position:sticky;top:0;z-index:10;background:#f6f7fb;padding-bottom:12px}.notice{padding:12px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e5e7eb;margin-top:10px;line-height:1.6}.resultLine{padding:8px 0;border-bottom:1px solid #e5e7eb}.nowrap{white-space:nowrap}.orderNoCell{display:flex;gap:8px;align-items:center}.moneyInput{width:120px}@media(max-width:760px){body{padding:16px 10px}.toolbar{align-items:stretch}.toolbar input,.toolbar select,.toolbar button{width:100%}.tableWrap{max-height:none}th,td{font-size:12px;padding:9px}.desktopOnly{display:none}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topBar">
    <div class="panel" style="margin-bottom:0">
      <div class="toolbar">
        <h2 style="margin:0;margin-right:auto">后台管理</h2>
        <span id="adminBadge" class="pill">加载中</span>
        <span id="refreshBadge" class="muted">未刷新</span>
        <button class="secondary" onclick="loadAll()">刷新全部</button>
        <button onclick="logout()">退出登录</button>
      </div>
      <p class="muted">效率优化版：批量确认收款 / 自动刷新 / 订单高亮 / 快速复制 / 筛选搜索。</p>
    </div>
  </div>

  <div class="panel">
    <div class="toolbar">
      <h3 style="margin:0;margin-right:auto">今日处理台</h3>
      <div class="switch"><input type="checkbox" id="autoRefreshToggle" checked onchange="toggleAutoRefresh()"><label for="autoRefreshToggle" class="muted">每 10 秒自动刷新</label></div>
      <button class="light" onclick="selectNeedConfirm()">选择待处理</button>
      <button class="okBtn" id="bulkBtn" onclick="bulkConfirm()">批量确认收款并发货</button>
    </div>
    <div class="stats" id="orderStats" style="margin-top:12px"></div>
    <div class="notice" id="bulkResult">提示：勾选订单后可以批量发货；已发货订单会自动跳过。</div>
  </div>

  <div class="panel"><h3>库存余量</h3><div id="stockSummary" class="grid">加载中...</div></div>

  <div id="inventoryWritePanel" class="panel hide">
    <h3>添加库存</h3>
    <div class="toolbar"><select id="addProduct"><option value="GPT">GPT</option><option value="CLAUDE">CLAUDE</option><option value="VIP">VIP</option><option value="MJ">MJ</option></select><button onclick="addStock()">添加库存</button></div>
    <textarea id="codesText" placeholder="一行一个卡密，例如：&#10;gpt-012&#10;gpt-013&#10;gpt-014"></textarea>
    <p class="muted">manager / super_admin 可添加库存；support 只读。</p>
  </div>

  <div class="panel"><h3>用户订单查询</h3><div class="toolbar"><input id="queryOrderNo" placeholder="输入订单号，例如 ORD-XXXX" style="width:300px"><button onclick="queryOrder()">查询</button></div><div id="queryResult" style="margin-top:12px">请输入订单号查询。</div></div>

  <div class="panel">
    <div class="toolbar">
      <h3 style="margin:0;margin-right:auto">订单列表</h3>
      <input id="searchInput" placeholder="搜索订单号 / 邮箱 / 商品" oninput="renderOrders()" style="width:240px">
      <select id="statusFilter" onchange="renderOrders()">
        <option value="all">全部订单</option>
        <option value="need_confirm">待确认/待发货</option>
        <option value="pending_payment">未付款</option>
        <option value="paid_pending">已付款待发货</option>
        <option value="delivered">已发货</option>
      </select>
      <button class="light" onclick="copySelectedOrderNos()">复制已选订单号</button>
    </div>
    <div class="tableWrap" style="margin-top:14px">
      <table><thead><tr><th><input type="checkbox" id="checkAll" onchange="toggleCheckAll(this.checked)"></th><th>订单号</th><th>邮箱</th><th>产品</th><th>订单状态</th><th>支付状态</th><th>发货状态</th><th>发货内容</th><th>时间</th><th>操作</th></tr></thead><tbody id="ordersBody"><tr><td colspan="10">加载中...</td></tr></tbody></table>
    </div>
  </div>

  <div id="adminsPanel" class="panel hide">
    <h3>多管理员系统</h3>
    <p class="muted">只有 super_admin 可以创建、改密码、禁用管理员。</p>
    <div class="row2">
      <input id="newAdminUsername" placeholder="新管理员账号">
      <input id="newAdminPassword" type="password" placeholder="新管理员密码，至少 6 位">
      <select id="newAdminRole"><option value="support">客服只读 support</option><option value="manager">运营管理员 manager</option><option value="super_admin">超级管理员 super_admin</option></select>
      <button onclick="createAdmin()">创建管理员</button>
    </div>
    <div style="margin-top:16px"><table><thead><tr><th>ID</th><th>账号</th><th>角色</th><th>状态</th><th>最后登录</th><th>操作</th></tr></thead><tbody id="adminsBody"><tr><td colspan="6">加载中...</td></tr></tbody></table></div>
  </div>
</div>
<script>
const API_BASE = window.location.origin;
const token = localStorage.getItem("admin_token");
let currentAdmin = JSON.parse(localStorage.getItem("admin_info") || "{}");
let allOrders = [];
let selectedOrders = new Set();
let autoTimer = null;
if(!token) window.location.href = "/static/login.html";
function authHeaders(extra={}){ return {"Authorization":"Bearer " + token, ...extra}; }
function hasPerm(p){ return (currentAdmin.permissions || []).includes(p); }
function logout(){ localStorage.removeItem("admin_token"); localStorage.removeItem("admin_info"); window.location.href="/static/login.html"; }
function normalize(v){ return String(v || "").toLowerCase(); }
function safe(v){ return v===null||v===undefined||v==="" ? "-" : String(v).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }
function statusClass(v){ const s=normalize(v); if(["paid","completed","delivered","success","finished","active"].includes(s)) return "ok"; if(["failed","cancelled","canceled","error","disabled"].includes(s)) return "danger"; return "warn"; }
function rowClass(o){ const delivered=isDelivered(o); if(delivered) return "deliveredRow"; if(normalize(o.payment_status)==="paid") return "paidRow"; return "pendingRow"; }
function isDelivered(o){ return ["delivered","completed","sent","success"].includes(normalize(o.delivery_status)); }
function canConfirm(o){ return hasPerm("orders:confirm") && !isDelivered(o) && o.can_confirm; }
async function parseJsonSafe(res){ const text=await res.text(); try{return text?JSON.parse(text):{}}catch{return {raw:text}} }
function getError(data){ if(typeof data?.detail==="string") return data.detail; if(data?.detail) return JSON.stringify(data.detail); return data?.raw || data?.error || JSON.stringify(data || {}); }
async function apiFetch(url, options={}){ const res=await fetch(url,{...options,headers:{...authHeaders(options.headers||{})}}); const data=await parseJsonSafe(res); if(res.status===401){ logout(); return; } if(!res.ok) throw new Error(getError(data)); return data; }
function nowText(){ return new Date().toLocaleTimeString(); }
async function copyText(text){ try{ await navigator.clipboard.writeText(text); }catch{ const ta=document.createElement("textarea"); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); } }
async function copyValue(value, label="内容"){ await copyText(value); showBulkResult(`已复制${label}：${safe(value)}`, "ok"); }
function showBulkResult(html, type=""){ document.getElementById("bulkResult").innerHTML = `<span class="${type}">${html}</span>`; }
async function loadMe(){ const data=await apiFetch(`${API_BASE}/admin/me`); currentAdmin=data.admin; localStorage.setItem("admin_info", JSON.stringify(currentAdmin)); document.getElementById("adminBadge").innerText=`${currentAdmin.username} / ${currentAdmin.role_name}`; document.getElementById("inventoryWritePanel").classList.toggle("hide", !hasPerm("inventory:write")); document.getElementById("adminsPanel").classList.toggle("hide", !hasPerm("admins:manage")); }
async function loadAll(){ try{ await loadMe(); await loadStock(); await loadOrders(); if(hasPerm("admins:manage")) await loadAdmins(); document.getElementById("refreshBadge").innerText=`已刷新 ${nowText()}`; }catch(e){ showBulkResult(e.message,"danger"); } }
async function loadStock(){ const box=document.getElementById("stockSummary"); box.innerHTML="加载中..."; const res=await fetch(`${API_BASE}/inventory/stats`); const data=await parseJsonSafe(res); if(!res.ok) throw new Error(getError(data)); box.innerHTML=(data.items||[]).map(i=>`<div class="card"><strong>${safe(i.product_code)}</strong><div>可用：<span class="${Number(i.available)>0?'ok':'danger'}">${safe(i.available)}</span></div><div>总数：${safe(i.total)}</div><div>已用：${safe(i.used)}</div></div>`).join(""); }
async function addStock(){ if(!hasPerm("inventory:write")){ alert("权限不足"); return; } const product=document.getElementById("addProduct").value; const codes=document.getElementById("codesText").value.trim(); if(!codes){alert("请输入卡密");return;} const data=await apiFetch(`${API_BASE}/inventory/add`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({product_code:product,codes})}); alert(`添加成功：${data.inserted} 条`); document.getElementById("codesText").value=""; await loadStock(); }
async function loadOrders(){ const tbody=document.getElementById("ordersBody"); tbody.innerHTML=`<tr><td colspan="10">加载中...</td></tr>`; const data=await apiFetch(`${API_BASE}/admin/orders`); allOrders=data.items||[]; selectedOrders.forEach(no=>{ if(!allOrders.some(o=>o.order_no===no && canConfirm(o))) selectedOrders.delete(no); }); renderStats(); renderOrders(); }
function renderStats(){ const total=allOrders.length; const delivered=allOrders.filter(isDelivered).length; const need=allOrders.filter(canConfirm).length; const paidPending=allOrders.filter(o=>normalize(o.payment_status)==="paid" && !isDelivered(o)).length; const pending=allOrders.filter(o=>!isDelivered(o) && normalize(o.payment_status)!=="paid").length; document.getElementById("orderStats").innerHTML=`<div class="stat">总订单：<b>${total}</b></div><div class="stat">待处理：<b class="danger">${need}</b></div><div class="stat">已付款待发货：<b class="warn">${paidPending}</b></div><div class="stat">未付款/待确认：<b class="blue">${pending}</b></div><div class="stat">已发货：<b class="ok">${delivered}</b></div>`; }
function filterOrders(){ const q=normalize(document.getElementById("searchInput").value); const filter=document.getElementById("statusFilter").value; return allOrders.filter(o=>{ const hit=!q || normalize(o.order_no).includes(q) || normalize(o.customer_email).includes(q) || normalize(o.product_code).includes(q); if(!hit) return false; if(filter==="need_confirm") return canConfirm(o); if(filter==="pending_payment") return !isDelivered(o) && normalize(o.payment_status)!=="paid"; if(filter==="paid_pending") return normalize(o.payment_status)==="paid" && !isDelivered(o); if(filter==="delivered") return isDelivered(o); return true; }); }
function renderOrders(){ const tbody=document.getElementById("ordersBody"); const items=filterOrders(); if(!items.length){ tbody.innerHTML=`<tr><td colspan="10">暂无订单</td></tr>`; return; } tbody.innerHTML=items.map(o=>{ const delivered=isDelivered(o); const able=canConfirm(o); const orderNo=safe(o.order_no); const checked=selectedOrders.has(o.order_no)?"checked":""; return `<tr class="${rowClass(o)} ${selectedOrders.has(o.order_no)?'selectedRow':''}"><td><input type="checkbox" ${checked} ${able?'':'disabled'} onchange="toggleOrder('${orderNo}', this.checked)"></td><td><div class="orderNoCell"><span>${orderNo}</span><button class="copyBtn" onclick="copyValue('${orderNo}','订单号')">复制</button></div></td><td>${safe(o.customer_email)}<br><button class="copyBtn" onclick="copyValue('${safe(o.customer_email)}','邮箱')">复制邮箱</button></td><td>${safe(o.product_code)}</td><td class="${statusClass(o.status)}">${safe(o.status)}</td><td class="${statusClass(o.payment_status)}">${safe(o.payment_status)}</td><td class="${statusClass(o.delivery_status)}">${safe(o.delivery_status)}</td><td>${safe(o.delivery_content)}</td><td class="nowrap">${safe(o.created_at)}</td><td><button class="smallBtn" ${able?"":"disabled"} onclick="confirmPaid('${orderNo}')">${delivered?"已发货":(able?"确认收款并发货":"不可操作")}</button></td></tr>`; }).join(""); document.getElementById("checkAll").checked = items.length>0 && items.filter(canConfirm).every(o=>selectedOrders.has(o.order_no)); }
function toggleOrder(orderNo, checked){ if(checked) selectedOrders.add(orderNo); else selectedOrders.delete(orderNo); renderOrders(); }
function toggleCheckAll(checked){ filterOrders().forEach(o=>{ if(canConfirm(o)){ if(checked) selectedOrders.add(o.order_no); else selectedOrders.delete(o.order_no); } }); renderOrders(); }
function selectNeedConfirm(){ selectedOrders.clear(); allOrders.filter(canConfirm).forEach(o=>selectedOrders.add(o.order_no)); document.getElementById("statusFilter").value="need_confirm"; renderOrders(); showBulkResult(`已选择 ${selectedOrders.size} 个待处理订单`, "ok"); }
async function copySelectedOrderNos(){ const arr=[...selectedOrders]; if(!arr.length){ alert("请先勾选订单"); return; } await copyText(arr.join("\n")); showBulkResult(`已复制 ${arr.length} 个订单号`, "ok"); }
async function confirmPaid(orderNo){ if(!confirm(`确认已收款并发货？\n订单号：${orderNo}`)) return; const data=await apiFetch(`${API_BASE}/admin/orders/confirm-paid`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({order_no:orderNo})}); showBulkResult("发货成功：" + safe(data.delivery_content || data.result?.content || data.msg), "ok"); selectedOrders.delete(orderNo); await loadAll(); }
async function bulkConfirm(){ const arr=[...selectedOrders]; if(!arr.length){ alert("请先勾选要处理的订单"); return; } if(!confirm(`确认批量收款并发货？\n共 ${arr.length} 单`)) return; const btn=document.getElementById("bulkBtn"); btn.disabled=true; btn.innerText="批量处理中..."; try{ const data=await apiFetch(`${API_BASE}/admin/orders/confirm-paid-bulk`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({order_nos:arr})}); const lines=(data.items||[]).map(i=>`<div class="resultLine"><b>${safe(i.order_no)}</b>：<span class="${i.ok?'ok':'danger'}">${i.ok?'成功':'失败'}</span> - ${safe(i.msg)} ${i.delivery_content?`<br>发货内容：${safe(i.delivery_content)}`:''}</div>`).join(""); showBulkResult(`批量完成：成功 ${data.success_count} 单，失败 ${data.failed_count} 单<br>${lines}`, data.failed_count?"warn":"ok"); selectedOrders.clear(); await loadAll(); }catch(e){ showBulkResult(e.message,"danger"); }finally{ btn.disabled=false; btn.innerText="批量确认收款并发货"; } }
async function queryOrder(){ const orderNo=document.getElementById("queryOrderNo").value.trim(); const box=document.getElementById("queryResult"); if(!orderNo){alert("请输入订单号");return;} box.innerHTML="查询中..."; const res=await fetch(`${API_BASE}/orders/${encodeURIComponent(orderNo)}`); const data=await parseJsonSafe(res); if(!res.ok){ box.innerHTML=`<span class="danger">查询失败：${safe(getError(data))}</span>`; return;} box.innerHTML=`<div>订单号：${safe(data.order_no)}</div><div>邮箱：${safe(data.customer_email)}</div><div>产品：${safe(data.product_code)}</div><div>订单状态：<span class="${statusClass(data.status)}">${safe(data.status)}</span></div><div>支付状态：<span class="${statusClass(data.payment_status)}">${safe(data.payment_status)}</span></div><div>发货状态：<span class="${statusClass(data.delivery_status)}">${safe(data.delivery_status)}</span></div><div>发货内容：${safe(data.delivery_content)}</div><div>时间：${safe(data.created_at)}</div>`; }
async function loadAdmins(){ const tbody=document.getElementById("adminsBody"); tbody.innerHTML=`<tr><td colspan="6">加载中...</td></tr>`; const data=await apiFetch(`${API_BASE}/admin/admins`); tbody.innerHTML=(data.items||[]).map(a=>`<tr><td>${a.id}</td><td>${safe(a.username)}</td><td>${safe(a.role_name)}<br><span class="muted">${safe(a.role)}</span></td><td class="${a.is_active?'ok':'danger'}">${a.is_active?'启用':'禁用'}</td><td>${safe(a.last_login_at)}</td><td><button class="secondary" onclick="resetAdminPassword(${a.id})">改密码</button> <button class="secondary" onclick="changeAdminRole(${a.id}, '${a.role}')">改角色</button> <button class="dangerBtn" onclick="toggleAdmin(${a.id}, ${a.is_active})" ${a.id===currentAdmin.id?'disabled':''}>${a.is_active?'禁用':'启用'}</button></td></tr>`).join(""); }
async function createAdmin(){ const username=document.getElementById("newAdminUsername").value.trim(); const password=document.getElementById("newAdminPassword").value; const role=document.getElementById("newAdminRole").value; const data=await apiFetch(`${API_BASE}/admin/admins`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password,role})}); alert("创建成功："+data.admin.username); document.getElementById("newAdminUsername").value=""; document.getElementById("newAdminPassword").value=""; await loadAdmins(); }
async function resetAdminPassword(id){ const password=prompt("输入新密码，至少 6 位"); if(!password) return; await apiFetch(`${API_BASE}/admin/admins/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({password})}); alert("密码已修改"); }
async function changeAdminRole(id, oldRole){ const role=prompt("输入新角色：super_admin / manager / support", oldRole); if(!role) return; await apiFetch(`${API_BASE}/admin/admins/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({role})}); alert("角色已修改"); await loadAdmins(); }
async function toggleAdmin(id, isActive){ if(!confirm(isActive?"确认禁用这个管理员？":"确认启用这个管理员？")) return; await apiFetch(`${API_BASE}/admin/admins/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({is_active:!isActive})}); await loadAdmins(); }
function toggleAutoRefresh(){ if(autoTimer){ clearInterval(autoTimer); autoTimer=null; } if(document.getElementById("autoRefreshToggle").checked){ autoTimer=setInterval(()=>loadOrders().catch(()=>{}),10000); } }
loadAll(); toggleAutoRefresh();
</script>
</body>
</html>
