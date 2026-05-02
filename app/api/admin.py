from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.db import get_db
from app.models.entities import Order
from app.services.email_service import send_email

router = APIRouter()


# ✅ 管理员确认收款（进入处理中）
@router.post("/admin/confirm-payment/{order_id}")
def confirm_payment(order_id: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 更新订单状态
    order.payment_status = "paid"
    order.status = "paid"
    order.delivery_status = "processing"
    order.updated_at = datetime.utcnow()

    db.commit()

    # ✅ 发送“处理中”邮件（已优化版本）
    subject = f"您的订单正在处理中：{order.order_id}"

    html_content = f"""
    <h2>您的订单正在处理中</h2>

    <p>您好，您的订单已成功支付，我们已收到款项。</p>

    <p><b>订单号：</b>{order.order_id}</p>
    <p><b>产品套餐：</b>{order.product_name}</p>
    <p><b>当前状态：</b>正在处理中</p>

    <p>
    我们正在为您进行开通操作，请耐心等待，一般会在短时间内完成。<br>
    <b style="color:red;">如超过30分钟未完成，请联系客服处理。</b>
    </p>

    <p>开通完成后，您将收到新的完成通知邮件。</p>

    <p>感谢您的支持！</p>
    """

    try:
        send_email(
            to_email=order.email,
            subject=subject,
            html_content=html_content
        )
    except Exception as e:
        print("邮件发送失败:", str(e))

    return {"message": "已确认收款，订单进入处理中"}


# ✅ 完成开通（发最终交付邮件）
@router.post("/admin/complete-order/{order_id}")
def complete_order(order_id: str, delivery_content: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    order.status = "completed"
    order.delivery_status = "delivered"
    order.delivery_content = delivery_content
    order.updated_at = datetime.utcnow()

    db.commit()

    subject = f"订单已完成：{order.order_id}"

    html_content = f"""
    <h2>订单已处理完成</h2>

    <p>您好，您的订单已处理完成，详情如下：</p>

    <p><b>订单号：</b>{order.order_id}</p>
    <p><b>产品套餐：</b>{order.product_name}</p>

    <p><b>交付内容：</b></p>
    <p style="background:#f5f5f5;padding:10px;border-radius:6px;">
    {delivery_content}
    </p>

    <p>感谢您的支持！</p>
    """

    try:
        send_email(
            to_email=order.email,
            subject=subject,
            html_content=html_content
        )
    except Exception as e:
        print("邮件发送失败:", str(e))

    return {"message": "订单已完成"}
