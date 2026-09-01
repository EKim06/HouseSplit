# HouseSplit

HouseSplit is a warm, responsive household expense ledger built with FastAPI, Jinja2, HTMX, SQLAlchemy, and SQLite. Roommates can share houses, split purchases exactly, see net balances, record settle-ups, manage categories, and explore spending analytics.

## Local setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install the application and development dependencies:

   ```bash
   pip install -e ".[dev]"
   ```

3. Copy `.env.example` to `.env` and replace the development secret with a long random value.
4. Apply the database migration and seed the default categories:

   ```bash
   alembic upgrade head
   python -m scripts.seed
   ```

5. Start the development server:

   ```bash
   uvicorn app.main:app --reload
   ```

Open `http://127.0.0.1:8000`.

For a populated preview, run `python -m scripts.demo`, then sign in with `erin@example.com` and `housesplit-demo`.

## Tests

```bash
pytest
```

The suite covers exact monetary splits, deterministic debt simplification, authentication, CSRF protection, protected routes, and the core house flow.

## Data and security notes

- Money is stored as integer cents; percentage inputs use decimal values and deterministic largest-remainder rounding.
- Passwords are hashed with Argon2. Sessions are signed, HTTP-only, same-site cookies. Set `HOUSE_SPLIT_SECURE_COOKIES=true` behind HTTPS.
- Every ledger route verifies house membership. Mutations use CSRF tokens.
- Balances are derived from purchases and settlements, never stored as mutable totals.
- Referenced custom categories are archived rather than deleted so historical purchases remain readable.

## PostgreSQL migration

Models use portable SQLAlchemy column types and foreign keys. To move to PostgreSQL, install a PostgreSQL driver, change `HOUSE_SPLIT_DATABASE_URL`, and run `alembic upgrade head`. Review indexes with production query plans and use a dedicated session secret and HTTPS cookie configuration.

## Project map

- `app/main.py` — routes, permissions, and form workflows
- `app/models.py` — relational ledger schema
- `app/services.py` — exact splitting, balance simplification, and analytics
- `app/templates/` and `app/static/` — responsive interface
- `alembic/` — database migration
- `scripts/` — repeatable seed and demo data
- `tests/` — ledger and application regression tests
