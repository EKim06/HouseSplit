from sqlalchemy.orm import Session

from app.database import Base, engine
from app.services import seed_default_categories


def main() -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_default_categories(db)
    print("HouseSplit default categories are ready.")


if __name__ == "__main__":
    main()

