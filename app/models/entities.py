from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.db import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(64), unique=True, index=True)

    product_code = Column(String(100))
    customer_email = Column(String(255))

    amount_usd = Column(Numeric(10, 2))
    currency = Column(String(20), default="USD")

    payment_status = Column(String(50), default="pending")
    status = Column(String(50), default="pending_payment")
    delivery_status = Column(String(50), default="pending")

    external_payment_id = Column(String(100))
    delivery_content = Column(Text)

    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class DeliveryRecord(Base):
    __tablename__ = "delivery_records"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))

    status = Column(String(50))
    content = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)


class MembershipEntitlement(Base):
    __tablename__ = "membership_entitlements"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True)

    product_code = Column(String(100))
    entitlement_code = Column(String(120))

    activation_result = Column(Text)
    is_active = Column(Boolean, default=True)

    starts_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
