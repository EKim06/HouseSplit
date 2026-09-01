from decimal import Decimal

import pytest

from app.services import LedgerError, equal_split, fixed_split, money_to_cents, percentage_split, simplify_debts


def test_money_is_cent_exact():
    assert money_to_cents("12.345") == 1235
    assert money_to_cents("0.01") == 1
    with pytest.raises(LedgerError):
        money_to_cents("0")


def test_equal_split_distributes_remainder_by_stable_id():
    assert equal_split(1000, [3, 1, 2]) == {1: 334, 2: 333, 3: 333}
    assert sum(equal_split(1, [10, 2, 7]).values()) == 1


def test_fixed_split_requires_exact_total():
    assert fixed_split(1000, {1: "4.25", 2: "5.75"}) == {1: 425, 2: 575}
    with pytest.raises(LedgerError, match="add up"):
        fixed_split(1000, {1: "4.00", 2: "5.00"})


def test_percentage_split_uses_largest_remainder():
    shares, percentages = percentage_split(1000, {1: "33.33", 2: "33.33", 3: "33.34"})
    assert shares == {1: 333, 2: 333, 3: 334}
    assert sum(shares.values()) == 1000
    assert percentages[3] == Decimal("33.34")


def test_percentage_split_rejects_invalid_total():
    with pytest.raises(LedgerError, match="100"):
        percentage_split(1000, {1: "40", 2: "40"})


def test_simplify_debts_nets_globally_and_is_deterministic():
    suggestions = simplify_debts({1: 800, 2: -500, 3: -300})
    assert [(s.from_user_id, s.to_user_id, s.amount_cents) for s in suggestions] == [(2, 1, 500), (3, 1, 300)]
    assert len(suggestions) <= 2


def test_simplify_debts_handles_settled_house():
    assert simplify_debts({1: 0, 2: 0}) == []

