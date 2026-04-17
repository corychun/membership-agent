from typing import Any


def run_risk_check(email: str, seats: int, amount: float, ip: str | None = None) -> dict[str, Any]:
    score = 0
    flags: list[str] = []

    disposable_domains = {"tempmail.com", "mailinator.com", "guerrillamail.com"}
    domain = email.split("@")[-1].lower()

    if domain in disposable_domains:
        score += 50
        flags.append("temp_email")

    if seats >= 10:
        score += 25
        flags.append("large_seat_count")

    if amount >= 500:
        score += 20
        flags.append("high_amount")

    if ip is None:
        score += 5
        flags.append("missing_ip")

    return {
        "risk_score": score,
        "flags": flags,
        "needs_manual_review": score >= 40,
    }
