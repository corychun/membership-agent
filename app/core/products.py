"""统一产品配置。

所有后端价格、USDT 收款金额、是否代开通、有效期都从这里读取，
避免前端、后台、支付映射各自维护导致金额不一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class Product:
    code: str
    category: str
    name: str
    price_cny: int
    amount_usd: float  # NOWPayments 收款金额，按 USDT 近似美元计价，优先使用整数价
    period: str
    period_days: int
    inventory: bool
    badge: str = ""
    desc: str = ""
    legacy: bool = False

    @property
    def activation(self) -> bool:
        return not self.inventory or "ACTIVATE" in self.code.upper()


PRODUCTS: list[Product] = [
    # ChatGPT
    Product("GPT_PLUS_1M", "ChatGPT", "ChatGPT Plus 独享账号", 180, 25, "1个月", 30, True, legacy=True),
    Product("GPT_ACTIVATE_1M", "ChatGPT", "ChatGPT Plus 月付代开通", 169, 26, "1个月", 30, False, "🔥 新用户首选", "官方订阅 · 人工开通 · 稳定不封号 · 售后保障。"),
    Product("GPT_ACTIVATE_1Y", "ChatGPT", "ChatGPT Plus 年付代开通", 1799, 270, "1年", 365, False, "⭐ 年付推荐", "官方订阅 · 人工开通 · 长期使用更省心，适合稳定用户。"),
    Product("GPT_PLUS_1Y", "ChatGPT", "ChatGPT Plus 独享年卡", 1799, 270, "1年", 365, True),
    Product("GPT_TEAM_1M", "ChatGPT", "ChatGPT Team 席位", 260, 36, "1个月", 30, True),

    # Claude
    Product("CLAUDE_PRO_1M", "Claude", "Claude Pro 独享账号", 200, 28, "1个月", 30, True, legacy=True),
    Product("CLAUDE_ACTIVATE_1M", "Claude", "Claude Pro 月付代开通", 169, 26, "1个月", 30, False, "官方月付", "官方订阅 · 人工开通 · 适合长期稳定使用。"),
    Product("CLAUDE_ACTIVATE_1Y", "Claude", "Claude Pro 年付代开通", 1799, 270, "1年", 365, False, "⭐ 官方年付", "官方年付订阅 · 人工开通 · 平均月成本更低。"),
    Product("CLAUDE_PRO_1Y", "Claude", "Claude Pro 独享年卡", 1799, 270, "1年", 365, True),

    # Midjourney
    Product("MJ_BASIC_1M", "Midjourney", "Midjourney Basic", 120, 20, "1个月", 30, False, "AI绘画入门", "官方订阅 · 人工开通 · 适合低频出图和基础设计。"),
    Product("MJ_STANDARD_1M", "Midjourney", "Midjourney Standard", 279, 45, "1个月", 30, False, "⭐ 最多人选择", "官方订阅 · 人工开通 · 适合设计素材、海报、创意图。"),
    Product("MJ_PRO_1M", "Midjourney", "Midjourney Pro", 519, 85, "1个月", 30, False, "🔥 高性价比", "官方订阅 · 人工开通 · 适合设计师和高频出图用户。"),
    Product("MJ_MEGA_1M", "Midjourney", "Midjourney Mega", 999, 160, "1个月", 30, False, "👑 工作室推荐", "官方订阅 · 人工开通 · 适合高频创作、团队和工作室用户。"),

    # Gemini
    Product("GEMINI_PLUS_1M", "Gemini", "Gemini Plus", 99, 18, "1个月", 30, False, "入门推荐", "官方订阅 · 人工开通 · 适合日常AI使用与轻度多模态需求。"),
    Product("GEMINI_PRO_1M", "Gemini", "Gemini Pro", 189, 30, "1个月", 30, False, "🔥 主推套餐", "官方订阅 · 人工开通 · 更高额度、更强模型能力，适合高频用户。"),
    Product("GEMINI_ULTRA_1M", "Gemini", "Gemini Ultra", 1899, 290, "1个月", 30, False, "👑 高端套餐", "官方最高级订阅 · 人工开通 · 顶级模型权限和最高调用额度。"),
]

# 历史订单兼容：不再前台展示，但后台、查询、发货仍能识别。
LEGACY_PRODUCTS: list[Product] = [
    Product("GPT_ACTIVATE_3M", "ChatGPT", "ChatGPT Plus 季卡代开通（历史订单）", 499, 69, "3个月", 90, False, legacy=True),
    Product("GPT_PLUS_3M", "ChatGPT", "ChatGPT Plus 独享季卡（历史库存）", 499, 69, "3个月", 90, True, legacy=True),
    Product("CLAUDE_ACTIVATE_3M", "Claude", "Claude Pro 季卡代开通（历史订单）", 499, 69, "3个月", 90, False, legacy=True),
    Product("CLAUDE_PRO_3M", "Claude", "Claude Pro 独享季卡（历史库存）", 560, 78, "3个月", 90, True, legacy=True),
    Product("PERPLEXITY_PRO_1M", "更多AI工具", "Perplexity Pro 代开通（历史订单）", 120, 17, "1个月", 30, True, legacy=True),
    Product("CURSOR_PRO_1M", "更多AI工具", "Cursor Pro 代开通（历史订单）", 150, 21, "1个月", 30, True, legacy=True),
    Product("AI_BUNDLE_1M", "组合套餐", "AI全家桶月卡（历史订单）", 300, 42, "1个月", 30, True, legacy=True),
]

ALL_PRODUCTS: list[Product] = PRODUCTS + LEGACY_PRODUCTS
PRODUCT_MAP: Dict[str, Product] = {p.code.upper(): p for p in ALL_PRODUCTS}


def normalize_product_code(code: str | None) -> str:
    return str(code or "").strip().upper()


def get_product(code: str | None) -> Optional[Product]:
    return PRODUCT_MAP.get(normalize_product_code(code))


def product_name(code: str | None) -> str:
    p = get_product(code)
    return f"{p.category} - {p.name}" if p else (str(code or "-") or "-")


def product_price_cny(code: str | None, default: int = 0) -> int:
    p = get_product(code)
    return p.price_cny if p else default


def product_amount_usd(code: str | None, default: float = 20) -> float:
    """返回 NOWPayments 使用的收款金额。

    项目里字段沿用 amount_usd，但实际用于 USDT/TRC20 支付时，
    可理解为“需要收取的 USDT 近似金额”。为了减少小数和汇率波动，
    当前配置统一使用整数金额。
    """
    p = get_product(code)
    return p.amount_usd if p else default


def product_period_days(code: str | None, default: int = 30) -> int:
    p = get_product(code)
    return p.period_days if p else default


def is_inventory_product(code: str | None) -> bool:
    p = get_product(code)
    return bool(p.inventory) if p else False


def is_activation_product(code: str | None) -> bool:
    normalized = normalize_product_code(code)
    p = get_product(normalized)
    return bool(p.activation) if p else "ACTIVATE" in normalized


def active_inventory_products() -> Iterable[Product]:
    return [p for p in PRODUCTS if p.inventory]


def active_product_codes() -> set[str]:
    return {p.code for p in PRODUCTS}


def all_product_codes() -> set[str]:
    return set(PRODUCT_MAP.keys())
