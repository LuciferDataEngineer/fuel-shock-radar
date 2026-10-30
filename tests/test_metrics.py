from datetime import date, timedelta

from fuel_shock.metrics import (
    regional_gap,
    retail_margin,
    status_from_margin,
    status_from_regional_gap,
    status_from_savings,
    status_from_spread,
    weekly_cycle,
    weekly_pass_through,
)


def test_status_thresholds():
    assert status_from_spread(13) == "high"
    assert status_from_spread(8) == "elevated"
    assert status_from_spread(3) == "calm"
    assert status_from_savings(9) == "high"
    assert status_from_savings(5) == "elevated"
    assert status_from_savings(2) == "calm"
    assert status_from_margin(12, 7) == "high"
    assert status_from_margin(9, 7) == "elevated"
    assert status_from_margin(7.5, 7) == "calm"
    assert status_from_regional_gap(30) == "high"
    assert status_from_regional_gap(15) == "elevated"
    assert status_from_regional_gap(5) == "calm"


def test_weekly_cycle_picks_tuesday_and_prices_a_tank():
    start = date(2026, 10, 5)  # Monday
    daily = []
    prices = {
        0: 200.0,
        1: 190.0,
        2: 220.0,
        3: 210.0,
        4: 205.0,
        5: 202.0,
        6: 201.0,
    }
    for offset in range(21):
        day = start + timedelta(days=offset)
        daily.append((day, prices[day.weekday()]))
    cycle = weekly_cycle(daily, weeks=3)
    assert cycle.cheapest_day == "Tuesday"
    assert cycle.peak_day == "Wednesday"
    assert cycle.spread_cpl == 30
    assert round(cycle.savings_aud, 2) == 16.5
    assert cycle.status_spread == "high"


def test_pass_through_is_symmetric_when_moves_match():
    weeks = []
    retail = 200.0
    wholesale = 160.0
    for index, move in enumerate((0, 10, -8, 4, -4)):
        retail += move
        wholesale += move
        weeks.append((date(2026, 1, 5) + timedelta(weeks=index), retail, wholesale))
    result = weekly_pass_through(weeks, minimum_move_cpl=0.5)
    assert result.judgement == "symmetric"
    assert result.up_weeks == 2
    assert result.down_weeks == 2


def test_regional_gap_weights_stations_and_names_the_dearest():
    day = date(2026, 10, 29)
    rows = [(day, "Metro", 200.0)] * 2
    rows += [(day, "Peel", 210.0)]
    rows += [(day, "Kimberley", 300.0)]
    gap = regional_gap(rows, end=day, days=7)
    assert gap.metro_cpl == 200
    assert gap.dearest_region == "Kimberley"
    assert gap.gap_cpl == 55  # mean(210, 300) - 200
    assert gap.status == "high"
