from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Category, House, HouseMembership, Purchase, Settlement, User


DEFAULT_CATEGORIES = ["Groceries", "Utilities", "Household Supplies", "Rent", "Furniture", "Cleaning", "Other"]


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class DebtSuggestion:
    from_user_id: int
    to_user_id: int
    amount_cents: int


def money_to_cents(value: str) -> int:
    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise LedgerError("Enter a valid amount.")
    cents = int(amount * 100)
    if cents <= 0:
        raise LedgerError("Amount must be greater than zero.")
    return cents


def equal_split(total_cents: int, user_ids: list[int]) -> dict[int, int]:
    ids = sorted(set(user_ids))
    if not ids:
        raise LedgerError("Choose at least one roommate.")
    base, remainder = divmod(total_cents, len(ids))
    return {user_id: base + (1 if i < remainder else 0) for i, user_id in enumerate(ids)}


def fixed_split(total_cents: int, values: dict[int, str]) -> dict[int, int]:
    result = {user_id: money_to_cents(value) for user_id, value in values.items()}
    if not result:
        raise LedgerError("Choose at least one roommate.")
    if sum(result.values()) != total_cents:
        raise LedgerError("Fixed shares must add up to the purchase total.")
    return result


def percentage_split(total_cents: int, values: dict[int, str]) -> tuple[dict[int, int], dict[int, Decimal]]:
    if not values:
        raise LedgerError("Choose at least one roommate.")
    try:
        percentages = {user_id: Decimal(value) for user_id, value in values.items()}
    except (InvalidOperation, ValueError):
        raise LedgerError("Enter valid percentages.")
    if any(value <= 0 for value in percentages.values()):
        raise LedgerError("Each percentage must be greater than zero.")
    if sum(percentages.values()) != Decimal("100"):
        raise LedgerError("Percentages must add up to 100%.")
    exact = {user_id: Decimal(total_cents) * value / Decimal(100) for user_id, value in percentages.items()}
    shares = {user_id: int(value.to_integral_value(rounding=ROUND_DOWN)) for user_id, value in exact.items()}
    remaining = total_cents - sum(shares.values())
    ranked = sorted(exact, key=lambda uid: (exact[uid] - shares[uid], -uid), reverse=True)
    for user_id in ranked[:remaining]:
        shares[user_id] += 1
    return shares, percentages


def seed_default_categories(db: Session) -> None:
    existing = set(db.scalars(select(Category.name).where(Category.house_id.is_(None))).all())
    for name in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(name=name, house_id=None))
    db.commit()


def member_users(db: Session, house_id: int) -> list[User]:
    return list(db.scalars(select(User).join(HouseMembership).where(HouseMembership.house_id == house_id).order_by(User.name, User.id)).all())


def available_categories(db: Session, house_id: int, include_inactive: bool = False) -> list[Category]:
    stmt = select(Category).where(or_(Category.house_id.is_(None), Category.house_id == house_id))
    if not include_inactive:
        stmt = stmt.where(Category.active.is_(True))
    return list(db.scalars(stmt.order_by(Category.house_id.desc(), Category.name)).all())


def ledger_net_positions(db: Session, house_id: int, exclude_settlement_id: int | None = None) -> dict[int, int]:
    members = member_users(db, house_id)
    net = {member.id: 0 for member in members}
    purchases = db.scalars(
        select(Purchase).where(Purchase.house_id == house_id).options(selectinload(Purchase.splits))
    ).all()
    for purchase in purchases:
        for split in purchase.splits:
            if split.user_id != purchase.paid_by_id:
                net[purchase.paid_by_id] += split.amount_owed_cents
                net[split.user_id] -= split.amount_owed_cents
    stmt = select(Settlement).where(Settlement.house_id == house_id)
    if exclude_settlement_id is not None:
        stmt = stmt.where(Settlement.id != exclude_settlement_id)
    for settlement in db.scalars(stmt):
        net[settlement.from_user_id] += settlement.amount_cents
        net[settlement.to_user_id] -= settlement.amount_cents
    return net


def simplify_debts(net: dict[int, int]) -> list[DebtSuggestion]:
    creditors = [[uid, amount] for uid, amount in net.items() if amount > 0]
    debtors = [[uid, -amount] for uid, amount in net.items() if amount < 0]
    creditors.sort(key=lambda item: (-item[1], item[0]))
    debtors.sort(key=lambda item: (-item[1], item[0]))
    suggestions: list[DebtSuggestion] = []
    ci = di = 0
    while ci < len(creditors) and di < len(debtors):
        amount = min(creditors[ci][1], debtors[di][1])
        suggestions.append(DebtSuggestion(debtors[di][0], creditors[ci][0], amount))
        creditors[ci][1] -= amount
        debtors[di][1] -= amount
        if creditors[ci][1] == 0:
            ci += 1
        if debtors[di][1] == 0:
            di += 1
    return suggestions


def house_analytics(db: Session, house_id: int) -> dict:
    members = member_users(db, house_id)
    names = {user.id: user.name for user in members}
    fronted = defaultdict(int)
    responsibility = defaultdict(int)
    member_category = defaultdict(lambda: defaultdict(int))
    category_totals = defaultdict(int)
    monthly_totals = defaultdict(int)
    purchases = db.scalars(
        select(Purchase).where(Purchase.house_id == house_id).options(
            selectinload(Purchase.splits), selectinload(Purchase.category)
        )
    ).all()
    for purchase in purchases:
        fronted[purchase.paid_by_id] += purchase.amount_cents
        category_totals[purchase.category.name] += purchase.amount_cents
        monthly_totals[purchase.purchased_on.strftime("%Y-%m")] += purchase.amount_cents
        for split in purchase.splits:
            responsibility[split.user_id] += split.amount_owed_cents
            member_category[split.user_id][purchase.category.name] += split.amount_owed_cents
    return {
        "total_cents": sum(p.amount_cents for p in purchases),
        "fronted": sorted(((names[uid], fronted[uid]) for uid in names), key=lambda x: (-x[1], x[0])),
        "responsibility": sorted(((names[uid], responsibility[uid]) for uid in names), key=lambda x: (-x[1], x[0])),
        "member_category": {names[uid]: dict(values) for uid, values in member_category.items()},
        "category_totals": dict(sorted(category_totals.items(), key=lambda x: (-x[1], x[0]))),
        "monthly_totals": dict(sorted(monthly_totals.items())),
    }
