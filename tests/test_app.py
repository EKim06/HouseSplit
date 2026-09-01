import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services import seed_default_categories


@pytest.fixture
def client():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    TestingSession = sessionmaker(bind=test_engine, expire_on_commit=False)
    with TestingSession() as db:
        seed_default_categories(db)

    def override_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def csrf(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def register(client, name="Erin", email="erin@example.com"):
    token = csrf(client, "/register")
    return client.post("/register", data={"csrf_token": token, "name": name, "email": email, "password": "strong-pass"}, follow_redirects=False)


def test_registration_and_house_creation(client):
    response = register(client)
    assert response.status_code == 303
    token = csrf(client, "/houses")
    response = client.post("/houses", data={"csrf_token": token, "name": "Sunday House"}, follow_redirects=False)
    assert response.status_code == 303
    dashboard = client.get(response.headers["location"])
    assert dashboard.status_code == 200
    assert "Sunday House" in dashboard.text
    assert "Everything is beautifully even" in dashboard.text


def test_csrf_is_required(client):
    response = client.post("/register", data={"name": "Erin", "email": "erin@example.com", "password": "strong-pass"})
    assert response.status_code == 403


def test_protected_route_redirects_to_login(client):
    response = client.get("/houses", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_invite_purchase_balance_and_settlement_flow(client):
    register(client, "Erin", "erin@example.com")
    token = csrf(client, "/houses")
    created = client.post("/houses", data={"csrf_token": token, "name": "Sunday House"}, follow_redirects=False)
    house_path = created.headers["location"]
    dashboard = client.get(house_path)
    invite_code = re.search(r'/join/([A-Za-z0-9_-]+)', dashboard.text).group(1)

    logout_token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text).group(1)
    client.post("/logout", data={"csrf_token": logout_token})
    register(client, "Sam", "sam@example.com")
    join = client.get(f"/join/{invite_code}")
    join_token = re.search(r'name="csrf_token" value="([^"]+)"', join.text).group(1)
    joined = client.post(f"/join/{invite_code}", data={"csrf_token": join_token}, follow_redirects=False)
    assert joined.status_code == 303

    form_page = client.get(f"{house_path}/purchases/new")
    form_token = re.search(r'name="csrf_token" value="([^"]+)"', form_page.text).group(1)
    erin_id = re.search(r'<option value="(\d+)"[^>]*>Erin', form_page.text).group(1)
    sam_id = re.search(r'<option value="(\d+)"[^>]*>Sam', form_page.text).group(1)
    groceries_id = re.search(r'<option value="(\d+)"[^>]*>Groceries', form_page.text).group(1)
    purchase = client.post(f"{house_path}/purchases", data={
        "csrf_token": form_token, "description": "Groceries", "amount": "10.01",
        "purchased_on": "2026-08-31", "paid_by_id": erin_id, "category_id": groceries_id,
        "participant_ids": [erin_id, sam_id], "split_method": "equal",
    }, follow_redirects=False)
    assert purchase.status_code == 303
    dashboard = client.get(house_path)
    assert "−$5.00" in dashboard.text

    settle = client.get(f"{house_path}/settle")
    assert "Sam" in settle.text and "Erin" in settle.text and "$5.00" in settle.text
    analytics = client.get(f"{house_path}/analytics")
    assert analytics.status_code == 200
    assert "Spending patterns" in analytics.text
    assert "$10.01" in analytics.text
    categories = client.get(f"{house_path}/categories")
    assert categories.status_code == 200
    assert "Household Supplies" in categories.text
