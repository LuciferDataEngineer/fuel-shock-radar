"""Decision metrics for the three questions the dashboard answers.

All prices in this module are cents per litre unless a field is named ``_aud``.
The weekly cycle uses calendar weekdays in Australia/Perth, which is how
FuelWatch dates the price that applies that day.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from fuel_shock.config import (
    CYCLE_WEEKS,
    GAP_ELEVATED,
    GAP_HIGH,
    MARGIN_DAYS,
    MARGIN_ELEVATED_ABOVE_MEDIAN,
    MARGIN_HIGH_ABOVE_MEDIAN,
    REGION_DAYS,
    SAVINGS_ELEVATED,
    SAVINGS_HIGH,
    SPREAD_ELEVATED,
    SPREAD_HIGH,
    TANK_LITRES,
    WEEKDAYS,
)


def status_from_spread(spread_cpl: float) -> str:
    if spread_cpl >= SPREAD_HIGH:
        return "high"
    if spread_cpl >= SPREAD_ELEVATED:
        return "elevated"
    return "calm"


def status_from_savings(savings_aud: float) -> str:
    if savings_aud >= SAVINGS_HIGH:
        return "high"
    if savings_aud >= SAVINGS_ELEVATED:
        return "elevated"
    return "calm"


def status_from_margin(current_cpl: float, median_cpl: float) -> str:
    gap = current_cpl - median_cpl
    if gap >= MARGIN_HIGH_ABOVE_MEDIAN:
        return "high"
    if gap >= MARGIN_ELEVATED_ABOVE_MEDIAN:
        return "elevated"
    return "calm"


def status_from_regional_gap(gap_cpl: float) -> str:
    if gap_cpl >= GAP_HIGH:
        return "high"
    if gap_cpl >= GAP_ELEVATED:
        return "elevated"
    return "calm"


@dataclass(frozen=True)
class Cycle:
    window_start: date
    window_end: date
    by_day: tuple[dict, ...]
    cheapest_day: str
    peak_day: str
    cheapest_cpl: float
    peak_cpl: float
    spread_cpl: float
    savings_aud: float
    status_spread: str
    status_savings: str


def weekly_cycle(daily: list[tuple[date, float]], weeks: int = CYCLE_WEEKS) -> Cycle:
    """Average Perth daily price by weekday over the last ``weeks`` weeks."""
    if not daily:
        raise ValueError("weekly cycle needs at least one daily price")
    ordered = sorted(daily)
    end = ordered[-1][0]
    start = end - timedelta(days=weeks * 7 - 1)
    window = [(day, price) for day, price in ordered if start <= day <= end]
    buckets: dict[int, list[float]] = defaultdict(list)
    for day, price in window:
        buckets[day.weekday()].append(price)
    by_day = []
    for index, name in enumerate(WEEKDAYS):
        prices = buckets.get(index) or []
        average = statistics.fmean(prices) if prices else float("nan")
        by_day.append({"day": name, "price_cpl": average, "n": len(prices)})
    ranked = [row for row in by_day if row["n"]]
    cheapest = min(ranked, key=lambda row: (row["price_cpl"], WEEKDAYS.index(row["day"])))
    peak = max(ranked, key=lambda row: (row["price_cpl"], -WEEKDAYS.index(row["day"])))
    spread = peak["price_cpl"] - cheapest["price_cpl"]
    savings = spread / 100.0 * TANK_LITRES
    return Cycle(
        window_start=start,
        window_end=end,
        by_day=tuple(by_day),
        cheapest_day=cheapest["day"],
        peak_day=peak["day"],
        cheapest_cpl=cheapest["price_cpl"],
        peak_cpl=peak["price_cpl"],
        spread_cpl=spread,
        savings_aud=savings,
        status_spread=status_from_spread(spread),
        status_savings=status_from_savings(savings),
    )


@dataclass(frozen=True)
class Margin:
    current_cpl: float
    median_cpl: float
    latest_day: date
    days: int
    status: str
    weekly: tuple[dict, ...]


def retail_margin(
    paired: list[tuple[date, float, float]],
    recent_days: int = MARGIN_DAYS,
) -> Margin:
    """``paired`` is (day, metro retail, Perth terminal gate), cents per litre."""
    if len(paired) < recent_days:
        raise ValueError("not enough days to measure the retail gap")
    ordered = sorted(paired)
    gaps = [retail - wholesale for _, retail, wholesale in ordered]
    recent = gaps[-recent_days:]
    current = statistics.fmean(recent)
    median = statistics.median(gaps)
    weekly: dict[date, list[tuple[float, float]]] = defaultdict(list)
    for day, retail, wholesale in ordered:
        week = day - timedelta(days=day.weekday())
        weekly[week].append((retail, wholesale))
    points = []
    for week in sorted(weekly):
        rows = weekly[week]
        points.append(
            {
                "week": week,
                "retail_cpl": statistics.fmean(retail for retail, _ in rows),
                "wholesale_cpl": statistics.fmean(wholesale for _, wholesale in rows),
            }
        )
    return Margin(
        current_cpl=current,
        median_cpl=float(median),
        latest_day=ordered[-1][0],
        days=recent_days,
        status=status_from_margin(current, float(median)),
        weekly=tuple(points),
    )


@dataclass(frozen=True)
class PassThrough:
    up_ratio: float | None
    down_ratio: float | None
    up_weeks: int
    down_weeks: int
    judgement: str


def weekly_pass_through(
    weekly: list[tuple[date, float, float]],
    minimum_move_cpl: float = 0.5,
) -> PassThrough:
    """Share of a weekly wholesale move that shows up in the weekly pump price.

    Weeks smooth out Perth's Wednesday spike, so this is not confused with the
    retail cycle itself. ``weekly`` rows are (week, retail, wholesale).
    """
    ordered = sorted(weekly)
    up: list[float] = []
    down: list[float] = []
    for previous, current in zip(ordered, ordered[1:]):
        move = current[2] - previous[2]
        if abs(move) < minimum_move_cpl:
            continue
        ratio = (current[1] - previous[1]) / move
        if move > 0:
            up.append(ratio)
        else:
            down.append(ratio)
    up_ratio = statistics.median(up) if up else None
    down_ratio = statistics.median(down) if down else None
    return PassThrough(
        up_ratio=up_ratio,
        down_ratio=down_ratio,
        up_weeks=len(up),
        down_weeks=len(down),
        judgement=_judge_pass_through(up_ratio, down_ratio),
    )


def _judge_pass_through(up_ratio: float | None, down_ratio: float | None) -> str:
    if up_ratio is None or down_ratio is None:
        return "unknown"
    if abs(up_ratio - down_ratio) < 0.10:
        return "symmetric"
    if up_ratio > down_ratio:
        return "rises_faster"
    return "falls_faster"


@dataclass(frozen=True)
class RegionGap:
    window_start: date
    window_end: date
    metro_cpl: float
    regional_cpl: float
    gap_cpl: float
    status: str
    by_region: tuple[dict, ...]
    dearest_region: str
    dearest_cpl: float


def regional_gap(
    station_days: list[tuple[date, str, float]],
    end: date | None = None,
    days: int = REGION_DAYS,
) -> RegionGap:
    """Station-weighted average unleaded price, metro against everywhere else."""
    if not station_days:
        raise ValueError("regional gap needs prices")
    last = end or max(day for day, _, _ in station_days)
    start = last - timedelta(days=days - 1)
    window = [
        (day, region, price)
        for day, region, price in station_days
        if start <= day <= last and region
    ]
    metro = [price for _, region, price in window if region == "Metro"]
    regional = [price for _, region, price in window if region != "Metro"]
    if not metro or not regional:
        raise ValueError("both metro and regional prices are required")
    buckets: dict[str, list[float]] = defaultdict(list)
    for _, region, price in window:
        buckets[region].append(price)
    by_region = tuple(
        {"region": region, "price_cpl": statistics.fmean(prices), "n": len(prices)}
        for region, prices in sorted(buckets.items(), key=lambda item: (-statistics.fmean(item[1]), item[0]))
    )
    dearest = by_region[0]
    metro_cpl = statistics.fmean(metro)
    regional_cpl = statistics.fmean(regional)
    gap = regional_cpl - metro_cpl
    return RegionGap(
        window_start=start,
        window_end=last,
        metro_cpl=metro_cpl,
        regional_cpl=regional_cpl,
        gap_cpl=gap,
        status=status_from_regional_gap(gap),
        by_region=by_region,
        dearest_region=dearest["region"],
        dearest_cpl=dearest["price_cpl"],
    )


def brent_change(observations: list[tuple[date, float]], years: int = 1) -> dict:
    ordered = sorted(pair for pair in observations if pair[1] is not None)
    latest_day, latest = ordered[-1]
    target = latest_day - timedelta(days=365 * years)
    earlier = [pair for pair in ordered if pair[0] <= target]
    if not earlier:
        earlier = ordered[:1]
    base_day, base = earlier[-1]
    return {
        "latest_day": latest_day,
        "latest_usd": latest,
        "base_day": base_day,
        "base_usd": base,
        "change_pct": (latest / base - 1.0) * 100.0,
    }


def average_between(
    daily: list[tuple[date, float]],
    start: date,
    end: date,
) -> float | None:
    prices = [price for day, price in daily if start <= day <= end]
    if not prices:
        return None
    return statistics.fmean(prices)

