import pytest

from app.calculations.tariff import (
    marginal_rate,
    settle_net_metering,
    slab_bill,
    validate_slabs,
)

# A telescopic tariff: 2/unit to 50, 3/unit to 100, 5/unit beyond.
SLABS = [
    {"upto": 50, "rate": 2.0},
    {"upto": 100, "rate": 3.0},
    {"upto": None, "rate": 5.0},
]


# --- slab billing ----------------------------------------------------------

@pytest.mark.parametrize("units, expected", [
    (0, 0),
    (30, 60),                       # 30 x 2
    (50, 100),                      # 50 x 2
    (75, 175),                      # 50 x 2 + 25 x 3
    (100, 250),                     # 50 x 2 + 50 x 3
    (150, 500),                     # 50 x 2 + 50 x 3 + 50 x 5
])
def test_slab_bill_is_telescopic(units, expected):
    assert slab_bill(units, SLABS) == pytest.approx(expected)


def test_escalation_scales_every_band():
    assert slab_bill(150, SLABS, escalation_factor=1.1) == pytest.approx(500 * 1.1)


def test_solar_saves_at_the_top_slab_not_the_average():
    # 150 units costs 500, so the average is 3.33/unit. Removing 50 units saves 250,
    # which is 5/unit: solar displaces the most expensive units first.
    saving = slab_bill(150, SLABS) - slab_bill(100, SLABS)
    assert saving == pytest.approx(250)
    assert saving / 50 > slab_bill(150, SLABS) / 150


@pytest.mark.parametrize("units, expected", [(30, 2.0), (50, 3.0), (75, 3.0), (150, 5.0)])
def test_marginal_rate(units, expected):
    assert marginal_rate(units, SLABS) == pytest.approx(expected)


# --- slab validation -------------------------------------------------------

def test_validate_accepts_a_well_formed_tariff():
    assert validate_slabs(SLABS)[-1]["upto"] is None


@pytest.mark.parametrize("slabs, reason", [
    ([], "at least one"),
    ([{"upto": 50, "rate": 2.0}], "open-ended"),
    ([{"upto": None, "rate": 2.0}, {"upto": 100, "rate": 3.0}], "only the final"),
    ([{"upto": 100, "rate": 2.0}, {"upto": 50, "rate": 3.0}], "increase"),
    ([{"upto": 50, "rate": -1}, {"upto": None, "rate": 3.0}], "negative"),
    ([{"upto": 50}, {"upto": None, "rate": 3.0}], "usable rate"),
])
def test_validate_rejects_malformed_tariffs(slabs, reason):
    with pytest.raises(ValueError, match=reason):
        validate_slabs(slabs)


# --- net metering settlement ----------------------------------------------

def test_surplus_banks_instead_of_being_sold():
    # All the generation arrives in month 1; the load comes in month 2.
    generation = [200.0] + [0.0] * 11
    consumption = [0.0, 150.0] + [0.0] * 10

    result = settle_net_metering(generation, consumption)

    # Banking means month 2 imports nothing despite generating nothing.
    assert result["monthly_imports"] == [0.0] * 12
    assert result["self_consumed_kwh"] == pytest.approx(150)
    assert result["banked_surplus_kwh"] == pytest.approx(50)


def test_generation_is_conserved():
    generation = [100.0] * 12
    consumption = [80.0] * 12

    result = settle_net_metering(generation, consumption)

    assert result["self_consumed_kwh"] + result["banked_surplus_kwh"] == pytest.approx(sum(generation))
    assert result["banked_surplus_kwh"] == pytest.approx(240)


def test_a_heavy_user_banks_nothing_and_still_imports():
    result = settle_net_metering([100.0] * 12, [300.0] * 12)

    assert result["banked_surplus_kwh"] == 0
    assert result["self_consumed_kwh"] == pytest.approx(1200)
    assert result["monthly_imports"] == pytest.approx([200.0] * 12)


def test_a_light_user_banks_almost_everything():
    result = settle_net_metering([100.0] * 12, [10.0] * 12)

    assert result["self_consumed_kwh"] == pytest.approx(120)
    assert result["banked_surplus_kwh"] == pytest.approx(1080)
    assert result["monthly_imports"] == [0.0] * 12


def test_both_series_must_cover_the_year():
    with pytest.raises(ValueError, match="12 months"):
        settle_net_metering([100.0] * 11, [80.0] * 12)
