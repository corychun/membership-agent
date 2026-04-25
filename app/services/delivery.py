import traceback
from app.models.entities import Order
from app.services.inventory import get_available_item, mark_item_used
from app.services.mail import send_email


def mark_paid_and_deliver(db, order: Order):
    """
    核心发货函数（最终稳定版）
    """

    try:
        # ✅ 防重复发货
        if str(order.delivery_status).lower() in ["delivered", "completed"]:
            return {
                "ok": True,
                "msg": "already delivered"
            }

        # ✅ 获取库存
        item = get_available_item(db, order.product_code)

        if not item:
            raise Exception("库存不足")

        # ✅ 标记库存已用
        mark_item_used(db, item.id)

        # ✅ 写入订单
        order.delivery_status = "delivered"
        order.status = "completed"
        order.delivery_content = item.content

        db.commit()
        db.refresh(order)

        # ✅ 发邮件（关键点）
        try:
            send_email(
                to_email=order.customer_email,
                subject="你的卡密已发货",
                content=f"""
你好，

你购买的产品已发货：

{item.content}

请妥善保存。
"""
            )
        except Exception as mail_err:
            print("邮件发送失败：")
            print(traceback.format_exc())

            # ⚠️ 不让邮件失败影响发货
            return {
                "ok": True,
                "msg": "发货成功，但邮件发送失败",
                "content": item.content
            }

        return {
            "ok": True,
            "msg": "发货成功",
            "content": item.content
        }

    except Exception as e:
        print("发货错误：")
        print(traceback.format_exc())

        raise Exception(f"发货失败: {str(e)}")
