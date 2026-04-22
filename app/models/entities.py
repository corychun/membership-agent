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
    code = Column(Text)  # 卡密 / 账号 / key

    is_used = Column(Integer, default=0)  # 0=未使用 1=已使用
    used_at = Column(DateTime)

    order_id = Column(Integer, ForeignKey("orders.id"))

    created_at = Column(DateTime, default=datetime.utcnow)
