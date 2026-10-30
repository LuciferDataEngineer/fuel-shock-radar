from datetime import date

from fuel_shock.metrics import Cycle, Margin, PassThrough, RegionGap
from fuel_shock.narrative import build_copy

JARGON = (
    "kafka",
    "debezium",
    "airflow",
    "duckdb",
    "parquet",
    "spark",
    "marquez",
    "redpanda",
    "great expectations",
    "delta lake",
)


def _copy():
    cycle = Cycle(
        window_start=date(2026, 7, 10),
        window_end=date(2026, 10, 29),
        by_day=(),
        cheapest_day="Tuesday",
        peak_day="Wednesday",
        cheapest_cpl=204.1,
        peak_cpl=217.6,
        spread_cpl=13.5,
        savings_aud=7.43,
        status_spread="high",
        status_savings="elevated",
    )
    margin = Margin(
        current_cpl=8.85,
        median_cpl=7.62,
        latest_day=date(2026, 10, 29),
        days=7,
        status="calm",
        weekly=(),
    )
    regions = RegionGap(
        window_start=date(2026, 10, 2),
        window_end=date(2026, 10, 29),
        metro_cpl=234.1,
        regional_cpl=255.6,
        gap_cpl=21.5,
        status="elevated",
        by_region=(),
        dearest_region="Kimberley",
        dearest_cpl=303.0,
    )
    passed = PassThrough(0.89, 0.92, 27, 23, "symmetric")
    brent = {"latest_usd": 123.1, "change_pct": 87.9}
    return build_copy(cycle, margin, regions, passed, brent, 36.6, 228.4, "Saturday")


def test_copy_answers_the_three_questions_in_plain_language():
    copy = _copy()
    assert copy["headline"] == "Tuesday is the day to fill in Perth."
    assert "$7.43" in copy["dek"]
    assert len(copy["cards"]) == 4
    assert copy["cards"][0]["value"] == "Tuesday"
    assert copy["cards"][0]["status"] == "high"
    assert copy["cards"][2]["status"] == "calm"
    assert "both reach the pump" in copy["cards"][2]["action"]
    assert "Kimberley" in copy["cards"][3]["action"]
    blob = " ".join(
        [copy["headline"], copy["dek"], copy["kicker"], *copy["chart_leads"].values()]
        + [card["action"] + card["detail"] + card["title"] for card in copy["cards"]]
    ).lower()
    for word in JARGON:
        assert word not in blob
