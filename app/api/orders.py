@router.post("/orders")
async def create_order(data: OrderCreate, db: AsyncSession = Depends(get_db)):
    order = Order(
        email=data.email,
        target_email=data.target_email,
        user_type=data.user_type,
        product_code=data.product_code,
        seats=data.seats,
        amount=20,  # 你现在是20 USD
        currency="USD",
        status="created",
        payment_status="unpaid"
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    return {
        "order_id": str(order.id),
        "status": order.status
    }
