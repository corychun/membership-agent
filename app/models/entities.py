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
