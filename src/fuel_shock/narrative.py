"""Plain-language copy for the dashboard. No pipeline vocabulary."""

from __future__ import annotations

from fuel_shock.config import (
    CPI_FUEL_YOY,
    CPI_PERIOD,
    CPI_SOURCE,
    CPI_TRANSPORT_YOY,
    CYCLE_WEEKS,
    REGION_DAYS,
    TANK_LITRES,
)
from fuel_shock.metrics import Cycle, Margin, PassThrough, RegionGap


def dollars(cents: float) -> float:
    return round(cents / 100.0, 2)


def cents(value: float) -> float:
    return round(value, 1)


def money(amount: float) -> str:
    return f"${amount:.2f}"


def status_word(status: str) -> str:
    return {"calm": "Calm", "elevated": "Elevated", "high": "High"}[status]


def _pct(value: float) -> str:
    return f"{round(value):.0f}%"


def pass_through_sentence(result: PassThrough) -> str:
    if result.judgement == "unknown":
        return "There were not enough wholesale moves to compare rises and falls."
    up = _pct(result.up_ratio * 100)
    down = _pct(result.down_ratio * 100)
    if result.judgement == "symmetric":
        return (
            f"Over a week, about {up} of a wholesale rise and {down} of a fall "
            "show up in the pump price."
        )
    if result.judgement == "rises_faster":
        return (
            f"Rises reach the pump faster than falls: about {up} of a weekly wholesale "
            f"rise is passed on, against {down} of a fall."
        )
    return (
        f"Falls are showing up at least as fully as rises: about {down} of a weekly "
        f"wholesale fall is passed on, against {up} of a rise."
    )


def build_copy(
    cycle: Cycle,
    margin: Margin,
    regions: RegionGap,
    passed: PassThrough,
    brent: dict,
    pump_year_change_pct: float | None,
    tomorrow_cpl: float | None,
    tomorrow_label: str | None,
) -> dict:
    savings = round(cycle.savings_aud, 2)
    gap = cents(regions.gap_cpl)
    margin_now = cents(margin.current_cpl)
    dearest_dollars = money(dollars(regions.dearest_cpl))
    cheap = cycle.cheapest_day
    peak = cycle.peak_day
    brent_pct = round(brent["change_pct"])
    brent_usd = f"${brent['latest_usd']:.0f}" if brent["latest_usd"] >= 100 else f"${brent['latest_usd']:.2f}"

    tomorrow_bit = ""
    if tomorrow_cpl is not None and tomorrow_label:
        tomorrow_bit = f" The price for {tomorrow_label} is posted at {money(dollars(tomorrow_cpl))}."

    if passed.judgement == "symmetric":
        margin_action = (
            f"{margin_now:.1f}c above wholesale, close to the past year. "
            "Rises and falls both reach the pump within a week."
        )
    elif passed.judgement == "rises_faster":
        margin_action = (
            f"{margin_now:.1f}c above wholesale. Weekly rises are reaching the pump "
            "more fully than falls."
        )
    elif passed.judgement == "falls_faster":
        margin_action = (
            f"{margin_now:.1f}c above wholesale. Weekly falls are being passed on "
            "at least as fully as rises."
        )
    else:
        margin_action = f"{margin_now:.1f}c above the Perth terminal price this week."

    year_bit = ""
    if pump_year_change_pct is not None:
        year_bit = f" Perth unleaded is up {round(pump_year_change_pct)}% on a year earlier."

    if margin.status == "calm":
        price_story = (
            "The higher prices are coming through wholesale. "
            "The gap over the terminal price is close to the past year."
        )
    elif margin.status == "elevated":
        price_story = "The gap between the pump price and wholesale is wider than usual."
    else:
        price_story = "The gap between the pump price and wholesale is much wider than the past year."

    return {
        "kicker": (
            f"Transport costs rose {CPI_TRANSPORT_YOY:.1f}% in {CPI_PERIOD}. "
            f"Automotive fuel rose {CPI_FUEL_YOY:.1f}%."
        ),
        "headline": f"{cheap} is the day to fill in Perth.",
        "dek": (
            f"The weekly spike is worth {money(savings)} on a {TANK_LITRES:.0f} litre tank. "
            f"Country pumps average {gap:.0f} cents a litre more than the city. "
            f"{price_story}"
        ),
        "cards": [
            {
                "id": "cheapest-day",
                "eyebrow": "Drivers",
                "title": "Cheapest day",
                "value": cheap,
                "detail": (
                    f"Perth unleaded, last {CYCLE_WEEKS} weeks. "
                    f"{peak} is the dearest.{tomorrow_bit}"
                ),
                "status": cycle.status_spread,
                "status_label": status_word(cycle.status_spread),
                "action": f"Fill on {cheap}. Avoid {peak}, when the Perth price jumps.",
            },
            {
                "id": "timing-save",
                "eyebrow": "Drivers",
                "title": "What timing saves",
                "value": money(savings),
                "detail": f"On a {TANK_LITRES:.0f} litre tank, {cheap} versus {peak}.",
                "status": cycle.status_savings,
                "status_label": status_word(cycle.status_savings),
                "action": f"Waiting for {cheap} instead of {peak} saves {money(savings)} a fill.",
            },
            {
                "id": "margin",
                "eyebrow": "Policy",
                "title": "Pump price above wholesale",
                "value": f"{margin_now:.1f}c",
                "detail": f"Perth unleaded minus the terminal price, last {margin.days} days.",
                "status": margin.status,
                "status_label": status_word(margin.status),
                "action": margin_action,
            },
            {
                "id": "regional-gap",
                "eyebrow": "Households",
                "title": "Country premium",
                "value": f"{gap:.0f}c",
                "detail": "Average unleaded outside Perth, minus the Perth average.",
                "status": regions.status,
                "status_label": status_word(regions.status),
                "action": (
                    f"Budget about {gap:.0f} cents a litre more outside Perth. "
                    f"{regions.dearest_region} is the dearest, near {dearest_dollars}."
                ),
            },
        ],
        "chart_leads": {
            "week": (
                f"Average Perth price by weekday. {cheap} is cheapest at "
                f"{money(dollars(cycle.cheapest_cpl))}; {peak} peaks at "
                f"{money(dollars(cycle.peak_cpl))}."
            ),
            "wholesale": (
                "Weekly average pump price and the Perth terminal price, so the "
                f"mid-week spike is smoothed out.{year_bit} Brent crude is {brent_usd} a barrel, "
                f"up {brent_pct}% on a year ago. {pass_through_sentence(passed)}"
            ),
            "regions": (
                f"Average advertised unleaded, last {REGION_DAYS} days. "
                "Each station counts equally."
            ),
        },
        "sources": {
            "cpi": CPI_SOURCE,
            "fuelwatch": "https://www.fuelwatch.wa.gov.au/retail/historic",
            "fuelwatch_daily": "https://www.fuelwatch.wa.gov.au/api/sites?fuelType=ULP",
            "terminal": "https://www.fuelwatch.wa.gov.au/industry/historic-terminal-gate-prices",
            "brent": "https://fred.stlouisfed.org/series/DCOILBRENTEU",
            "licence": "https://creativecommons.org/licenses/by/4.0/",
        },
    }
