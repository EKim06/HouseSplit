from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import Category, House, HouseMembership, Purchase, PurchaseSplit, User
from app.security import hash_password
from app.services import seed_default_categories


def main() -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_default_categories(db)
        if db.scalar(select(User).where(User.email == "erin@example.com")):
            print("Demo already exists: erin@example.com / housesplit-demo")
            return
        users = [User(name=name, email=f"{name.lower()}@example.com", password_hash=hash_password("housesplit-demo")) for name in ("Erin", "Sam", "Maya")]
        db.add_all(users)
        db.flush()
        house = House(name="Sunday House", invite_code="sunday-house-demo", created_by_id=users[0].id)
        db.add(house)
        db.flush()
        db.add_all([HouseMembership(user_id=user.id, house_id=house.id) for user in users])
        categories = {category.name: category for category in db.scalars(select(Category).where(Category.house_id.is_(None))).all()}
        fixtures = [
            ("Weekend groceries", 8642, "Groceries", users[0], [2881, 2881, 2880], 0),
            ("August electricity", 14218, "Utilities", users[1], [4739, 4739, 4740], 7),
            ("Kitchen restock", 3960, "Household Supplies", users[2], [1320, 1320, 1320], 16),
            ("Living room lamp", 7400, "Furniture", users[0], [3700, 3700], 35),
        ]
        for description, amount, category, payer, shares, days_ago in fixtures:
            purchase = Purchase(house_id=house.id, paid_by_id=payer.id, amount_cents=amount, category_id=categories[category].id, description=description, purchased_on=date.today() - timedelta(days=days_ago), split_method="equal", created_by_id=payer.id, updated_by_id=payer.id)
            selected_users = users if len(shares) == 3 else [users[0], users[2]]
            purchase.splits = [PurchaseSplit(user_id=user.id, amount_owed_cents=share) for user, share in zip(selected_users, shares)]
            db.add(purchase)
        db.commit()
    print("Demo ready: erin@example.com / housesplit-demo")


if __name__ == "__main__":
    main()
