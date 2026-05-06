from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from app.core.db import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(64), unique=True, index=True)

    product_code = Column(String(100))
    customer_email = Column(String(255))

    payment_status = Column(String(50), default="pending")
    status = Column(String(50), default="pending_payment")
    delivery_status = Column(String(50), default="pending")

    delivery_content = Column(Text)

    # 支付方式标准化与人工确认资料。
    # 这些字段只用于展示和后台确认，不影响原有下单、库存、发货流程。
    payment_method = Column(String(50), default="unknown")
    payment_proof_url = Column(String(500))
    payment_proof_status = Column(String(50), default="not_uploaded")
    payment_proof_checked_at = Column(DateTime)
    payment_proof_checked_by = Column(String(80))
    admin_note = Column(Text)
    payment_confirm_note = Column(Text)
    confirmed_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)


class DeliveryRecord(Base):
    __tablename__ = "delivery_records"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))

    status = Column(String(50))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class MembershipEntitlement(Base):
    __tablename__ = "membership_entitlements"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))

    entitlement_code = Column(String(100))
    activation_result = Column(Text)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True)

    product_code = Column(String(100), index=True)
    code = Column(Text)

    is_used = Column(Integer, default=0)
    used_at = Column(DateTime)

    order_id = Column(Integer, ForeignKey("orders.id"))

    created_at = Column(DateTime, default=datetime.utcnow)


class InventoryLog(Base):
    __tablename__ = "inventory_logs"

    id = Column(Integer, primary_key=True)

    admin_id = Column(Integer, ForeignKey("admin_users.id"))
    admin_name = Column(String(80))

    action = Column(String(50))  # add / delete
    product_code = Column(String(100))

    quantity = Column(Integer)
    detail = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), default="support", nullable=False)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)



class AdminLoginAttempt(Base):
    __tablename__ = "admin_login_attempts"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), index=True)
    ip = Column(String(80), index=True)
    success = Column(Integer, default=0)
    reason = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)


class SupportSession(Base):
    __tablename__ = "support_sessions"

    id = Column(Integer, primary_key=True)
    session_no = Column(String(64), unique=True, index=True, nullable=False)

    customer_email = Column(String(255))
    order_no = Column(String(64), index=True)
    status = Column(String(30), default="open")

    assigned_admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("support_sessions.id"), index=True, nullable=False)

    sender_type = Column(String(30), nullable=False)
    sender_name = Column(String(100))
    content = Column(Text, nullable=False)

    is_read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProductConfigSnapshot(Base):
    __tablename__ = "product_config_snapshots"

    id = Column(Integer, primary_key=True)
    product_code = Column(String(100), index=True)
    product_name = Column(String(255))
    category = Column(String(80))
    price_cny = Column(Integer)
    amount_usd = Column(String(50))
    period = Column(String(50))
    inventory = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    updated_by = Column(String(80))
    updated_at = Column(DateTime, default=datetime.utcnow)


class SystemErrorLog(Base):
    __tablename__ = "system_error_logs"

    id = Column(Integer, primary_key=True)
    source = Column(String(80), index=True)
    level = Column(String(30), default="error")
    message = Column(Text)
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class OrderLog(Base):
    __tablename__ = "order_logs"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(64), index=True)
    admin_id = Column(Integer, nullable=True)
    admin_name = Column(String(80), nullable=True)
    action = Column(String(80), index=True)
    before_status = Column(String(120), nullable=True)
    after_status = Column(String(120), nullable=True)
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class RenewalTask(Base):
    __tablename__ = "renewal_tasks"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(64), unique=True, index=True)
    product_code = Column(String(100), index=True)
    customer_email = Column(String(255))
    period_days = Column(Integer, default=30)
    due_at = Column(DateTime, index=True)
    status = Column(String(50), default="active", index=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
