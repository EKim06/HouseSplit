from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from email_validator import EmailNotValidError, validate_email
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import Category, House, HouseMembership, Purchase, PurchaseSplit, Settlement, User
from app.security import csrf_token, hash_password, require_csrf, verify_password
from app.services import (
    LedgerError,
    available_categories,
    equal_split,
    fixed_split,
    house_analytics,
    ledger_net_positions,
    member_users,
    money_to_cents,
    percentage_split,
    seed_default_categories,
    simplify_debts,
)


ROOT = Path(__file__).parent
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_db:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            seed_default_categories(db)
    yield


app = FastAPI(title="HouseSplit", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="housesplit_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def format_money(cents: int) -> str:
    sign = "−" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


templates.env.filters["money"] = format_money
templates.env.filters["rjust"] = lambda value, width, fill=" ": str(value).rjust(width, fill)
templates.env.globals["today"] = date.today


def render(name: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(
        request=context["request"], name=name, context=context, status_code=status_code
    )


def redirect(url: str, status_code: int = status.HTTP_303_SEE_OTHER) -> RedirectResponse:
    return RedirectResponse(url, status_code=status_code)


def flash(request: Request, message: str, kind: str = "success") -> None:
    request.session.setdefault("flashes", []).append({"message": message, "kind": kind})


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


def require_house(db: Session, user: User, house_id: int) -> House:
    house = db.scalar(
        select(House).join(HouseMembership).where(
            House.id == house_id, HouseMembership.user_id == user.id
        )
    )
    if not house:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return house


def base_context(request: Request, db: Session, user: User | None = None, **extra) -> dict:
    user = user or current_user(request, db)
    houses = []
    if user:
        houses = list(db.scalars(
            select(House).join(HouseMembership).where(HouseMembership.user_id == user.id).order_by(House.name)
        ).all())
    context = {
        "request": request,
        "current_user": user,
        "houses": houses,
        "csrf_token": csrf_token(request),
        "flashes": request.session.pop("flashes", []),
    }
    context.update(extra)
    return context


@app.exception_handler(401)
async def unauthenticated(_: Request, __):
    return redirect("/login", status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        membership = db.scalar(select(HouseMembership).where(HouseMembership.user_id == user.id).order_by(HouseMembership.joined_at))
        return redirect(f"/houses/{membership.house_id}" if membership else "/houses")
    return render("landing.html", base_context(request, db))


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/houses")
    return render("auth.html", base_context(request, db, mode="register"))


@app.post("/register")
async def register(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    name = str(form.get("name", "")).strip()
    password = str(form.get("password", ""))
    try:
        email = validate_email(str(form.get("email", "")), check_deliverability=False).normalized.lower()
        if len(name) < 2:
            raise ValueError("Enter your name.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        user = User(name=name[:100], email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
    except EmailNotValidError:
        return render("auth.html", base_context(request, db, mode="register", error="Enter a valid email address.", values=form), status_code=422)
    except ValueError as exc:
        return render("auth.html", base_context(request, db, mode="register", error=str(exc), values=form), status_code=422)
    except IntegrityError:
        db.rollback()
        return render("auth.html", base_context(request, db, mode="register", error="An account with that email already exists.", values=form), status_code=409)
    join_code = request.session.get("join_after_login")
    request.session.clear()
    request.session["user_id"] = user.id
    flash(request, f"Welcome home, {user.name.split()[0]}!")
    if join_code:
        return redirect(f"/join/{join_code}")
    return redirect("/houses")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/houses")
    return render("auth.html", base_context(request, db, mode="login"))


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    email = str(form.get("email", "")).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(str(form.get("password", "")), user.password_hash):
        return render("auth.html", base_context(request, db, mode="login", error="Email or password is incorrect.", values=form), status_code=401)
    join_code = request.session.get("join_after_login")
    request.session.clear()
    request.session["user_id"] = user.id
    flash(request, f"Good to see you, {user.name.split()[0]}.")
    if join_code:
        return redirect(f"/join/{join_code}")
    membership = db.scalar(select(HouseMembership).where(HouseMembership.user_id == user.id).order_by(HouseMembership.joined_at))
    return redirect(f"/houses/{membership.house_id}" if membership else "/houses")


@app.post("/logout")
async def logout(request: Request):
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    request.session.clear()
    return redirect("/")


@app.get("/houses", response_class=HTMLResponse)
def houses_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return render("houses.html", base_context(request, db, user))


@app.post("/houses")
async def create_house(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    name = str(form.get("name", "")).strip()
    if len(name) < 2:
        return render("houses.html", base_context(request, db, user, error="Give your house a name."), status_code=422)
    house = House(name=name[:120], invite_code=secrets.token_urlsafe(24), created_by_id=user.id)
    db.add(house)
    db.flush()
    db.add(HouseMembership(user_id=user.id, house_id=house.id))
    db.commit()
    flash(request, f"{house.name} is ready. Invite your roommates when you’re ready.")
    return redirect(f"/houses/{house.id}")


@app.get("/join/{invite_code}", response_class=HTMLResponse)
def join_page(invite_code: str, request: Request, db: Session = Depends(get_db)):
    house = db.scalar(select(House).where(House.invite_code == invite_code))
    if not house:
        raise HTTPException(status_code=404)
    user = current_user(request, db)
    if not user:
        request.session["join_after_login"] = invite_code
        return redirect("/register")
    existing = db.scalar(select(HouseMembership).where(HouseMembership.user_id == user.id, HouseMembership.house_id == house.id))
    return render("join.html", base_context(request, db, user, house=house, existing=existing))


@app.post("/join/{invite_code}")
async def join_house(invite_code: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    house = db.scalar(select(House).where(House.invite_code == invite_code))
    if not house:
        raise HTTPException(status_code=404)
    existing = db.scalar(select(HouseMembership).where(HouseMembership.user_id == user.id, HouseMembership.house_id == house.id))
    if not existing:
        db.add(HouseMembership(user_id=user.id, house_id=house.id))
        db.commit()
        flash(request, f"You joined {house.name}.")
    return redirect(f"/houses/{house.id}")


def dashboard_context(request: Request, db: Session, user: User, house: House) -> dict:
    members = member_users(db, house.id)
    names = {member.id: member.name for member in members}
    net = ledger_net_positions(db, house.id)
    suggestions = simplify_debts(net)
    purchases = list(db.scalars(
        select(Purchase).where(Purchase.house_id == house.id).options(selectinload(Purchase.category), selectinload(Purchase.payer)).order_by(Purchase.purchased_on.desc(), Purchase.id.desc()).limit(8)
    ).all())
    settlements = list(db.scalars(
        select(Settlement).where(Settlement.house_id == house.id).options(selectinload(Settlement.from_user), selectinload(Settlement.to_user)).order_by(Settlement.settled_on.desc(), Settlement.id.desc()).limit(5)
    ).all())
    user_suggestions = [s for s in suggestions if user.id in (s.from_user_id, s.to_user_id)]
    return base_context(request, db, user, active_house=house, members=members, member_names=names, net=net, user_balance=net.get(user.id, 0), suggestions=suggestions, user_suggestions=user_suggestions, purchases=purchases, settlements=settlements)


@app.get("/houses/{house_id}", response_class=HTMLResponse)
def dashboard(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    return render("dashboard.html", dashboard_context(request, db, user, house))


def purchase_context(request: Request, db: Session, user: User, house: House, purchase: Purchase | None = None, error: str | None = None, values=None) -> dict:
    return base_context(request, db, user, active_house=house, members=member_users(db, house.id), categories=available_categories(db, house.id), purchase=purchase, error=error, values=values)


@app.get("/houses/{house_id}/purchases/new", response_class=HTMLResponse)
def new_purchase_page(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    return render("purchase_form.html", purchase_context(request, db, user, house))


def parse_purchase_form(form, member_ids: set[int], total_cents: int):
    try:
        participant_ids = sorted({int(value) for value in form.getlist("participant_ids")})
    except ValueError:
        raise LedgerError("Choose valid roommates.")
    if not participant_ids or not set(participant_ids).issubset(member_ids):
        raise LedgerError("Choose at least one current house member.")
    method = str(form.get("split_method", "equal"))
    percentages = {}
    if method == "equal":
        shares = equal_split(total_cents, participant_ids)
    elif method == "fixed":
        shares = fixed_split(total_cents, {uid: str(form.get(f"share_{uid}", "")) for uid in participant_ids})
    elif method == "percentage":
        shares, percentages = percentage_split(total_cents, {uid: str(form.get(f"share_{uid}", "")) for uid in participant_ids})
    else:
        raise LedgerError("Choose a valid split method.")
    return method, shares, percentages


async def save_purchase(request: Request, db: Session, user: User, house: House, purchase: Purchase | None = None):
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    members = member_users(db, house.id)
    member_ids = {member.id for member in members}
    try:
        description = str(form.get("description", "")).strip()
        if not description:
            raise LedgerError("Add a short description.")
        total_cents = money_to_cents(str(form.get("amount", "")))
        paid_by_id = int(str(form.get("paid_by_id", "")))
        category_id = int(str(form.get("category_id", "")))
        if paid_by_id not in member_ids:
            raise LedgerError("Choose a current house member as payer.")
        category = db.scalar(select(Category).where(Category.id == category_id, Category.active.is_(True), or_(Category.house_id.is_(None), Category.house_id == house.id)))
        if not category:
            raise LedgerError("Choose an available category.")
        purchased_on = date.fromisoformat(str(form.get("purchased_on", "")))
        method, shares, percentages = parse_purchase_form(form, member_ids, total_cents)
    except (LedgerError, ValueError) as exc:
        return render("purchase_form.html", purchase_context(request, db, user, house, purchase, str(exc), form), status_code=422)
    if purchase is None:
        purchase = Purchase(house_id=house.id, created_by_id=user.id, updated_by_id=user.id)
        db.add(purchase)
    else:
        purchase.splits.clear()
    purchase.description = description[:200]
    purchase.amount_cents = total_cents
    purchase.paid_by_id = paid_by_id
    purchase.category_id = category_id
    purchase.purchased_on = purchased_on
    purchase.split_method = method
    purchase.updated_by_id = user.id
    for uid, amount in shares.items():
        purchase.splits.append(PurchaseSplit(user_id=uid, amount_owed_cents=amount, percentage=percentages.get(uid)))
    db.commit()
    flash(request, "Purchase saved to the house ledger.")
    return redirect(f"/houses/{house.id}")


@app.post("/houses/{house_id}/purchases")
async def create_purchase(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    return await save_purchase(request, db, user, house)


@app.get("/houses/{house_id}/purchases/{purchase_id}/edit", response_class=HTMLResponse)
def edit_purchase_page(house_id: int, purchase_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    purchase = db.scalar(select(Purchase).where(Purchase.id == purchase_id, Purchase.house_id == house.id).options(selectinload(Purchase.splits)))
    if not purchase:
        raise HTTPException(status_code=404)
    return render("purchase_form.html", purchase_context(request, db, user, house, purchase))


@app.post("/houses/{house_id}/purchases/{purchase_id}")
async def update_purchase(house_id: int, purchase_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    purchase = db.scalar(select(Purchase).where(Purchase.id == purchase_id, Purchase.house_id == house.id).options(selectinload(Purchase.splits)))
    if not purchase:
        raise HTTPException(status_code=404)
    return await save_purchase(request, db, user, house, purchase)


@app.post("/houses/{house_id}/purchases/{purchase_id}/delete")
async def remove_purchase(house_id: int, purchase_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    purchase = db.scalar(select(Purchase).where(Purchase.id == purchase_id, Purchase.house_id == house.id))
    if not purchase:
        raise HTTPException(status_code=404)
    db.delete(purchase)
    db.commit()
    flash(request, "Purchase removed from the ledger.")
    return redirect(f"/houses/{house.id}")


@app.get("/houses/{house_id}/settle", response_class=HTMLResponse)
def settle_page(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    members = member_users(db, house.id)
    net = ledger_net_positions(db, house.id)
    suggestions = simplify_debts(net)
    settlements = list(db.scalars(select(Settlement).where(Settlement.house_id == house.id).options(selectinload(Settlement.from_user), selectinload(Settlement.to_user)).order_by(Settlement.settled_on.desc(), Settlement.id.desc())).all())
    return render("settle.html", base_context(request, db, user, active_house=house, members=members, member_names={m.id: m.name for m in members}, net=net, suggestions=suggestions, settlements=settlements))


@app.post("/houses/{house_id}/settlements")
async def create_settlement(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    try:
        from_id = int(str(form.get("from_user_id", "")))
        to_id = int(str(form.get("to_user_id", "")))
        amount = money_to_cents(str(form.get("amount", "")))
        match = next((s for s in simplify_debts(ledger_net_positions(db, house.id)) if s.from_user_id == from_id and s.to_user_id == to_id), None)
        if not match or amount > match.amount_cents:
            raise LedgerError("That balance changed. Refresh and use the latest settle-up amount.")
        settled_on = date.fromisoformat(str(form.get("settled_on", "")))
    except (LedgerError, ValueError) as exc:
        flash(request, str(exc), "error")
        return redirect(f"/houses/{house.id}/settle")
    db.add(Settlement(house_id=house.id, from_user_id=from_id, to_user_id=to_id, amount_cents=amount, settled_on=settled_on, method=str(form.get("method", "")).strip()[:60] or None, note=str(form.get("note", "")).strip()[:500] or None, created_by_id=user.id, updated_by_id=user.id))
    db.commit()
    flash(request, "Settlement recorded. Balances are up to date.")
    return redirect(f"/houses/{house.id}/settle")


@app.post("/houses/{house_id}/settlements/{settlement_id}/delete")
async def remove_settlement(house_id: int, settlement_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    settlement = db.scalar(select(Settlement).where(Settlement.id == settlement_id, Settlement.house_id == house.id))
    if not settlement:
        raise HTTPException(status_code=404)
    db.delete(settlement)
    db.commit()
    flash(request, "Settlement removed; balances were recalculated.")
    return redirect(f"/houses/{house.id}/settle")


@app.get("/houses/{house_id}/categories", response_class=HTMLResponse)
def categories_page(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    return render("categories.html", base_context(request, db, user, active_house=house, categories=available_categories(db, house.id, True)))


@app.post("/houses/{house_id}/categories")
async def create_category(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    name = str(form.get("name", "")).strip()
    if not name:
        flash(request, "Enter a category name.", "error")
    elif db.scalar(select(Category).where(Category.house_id == house.id, Category.name == name)):
        flash(request, "That category already exists in this house.", "error")
    else:
        db.add(Category(house_id=house.id, name=name[:80]))
        db.commit()
        flash(request, f"{name[:80]} added.")
    return redirect(f"/houses/{house.id}/categories")


@app.post("/houses/{house_id}/categories/{category_id}")
async def update_category(house_id: int, category_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    category = db.scalar(select(Category).where(Category.id == category_id, Category.house_id == house.id))
    if not category:
        raise HTTPException(status_code=404)
    action = str(form.get("action", "rename"))
    if action == "archive":
        category.active = not category.active
        message = "restored" if category.active else "archived"
    else:
        name = str(form.get("name", "")).strip()
        if not name:
            flash(request, "Category name cannot be empty.", "error")
            return redirect(f"/houses/{house.id}/categories")
        category.name = name[:80]
        message = "renamed"
    try:
        db.commit()
        flash(request, f"Category {message}.")
    except IntegrityError:
        db.rollback()
        flash(request, "That category name is already in use.", "error")
    return redirect(f"/houses/{house.id}/categories")


@app.get("/houses/{house_id}/analytics", response_class=HTMLResponse)
def analytics_page(house_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    house = require_house(db, user, house_id)
    analytics = house_analytics(db, house.id)
    return render("analytics.html", base_context(request, db, user, active_house=house, analytics=analytics))
