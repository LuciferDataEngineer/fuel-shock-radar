"""Paths, windows, and the thresholds behind the dashboard status colours."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
CURATED = DATA / "curated"
SERVING = DATA / "serving"
SITE = ROOT / "site"
DASHBOARD_JSON = SITE / "data" / "dashboard.json"
LINEAGE_DIR = ROOT / "lineage" / "events"
QUALITY_DOCS = ROOT / "quality" / "data_docs"

# Retail months covering the year to the September 2026 CPI print, plus October.
RETAIL_START = (2025, 10)
RETAIL_END = (2026, 10)
WHOLESALE_YEARS = (2025, 2026)

FUELWATCH_API = "https://www.fuelwatch.wa.gov.au/api"
RETAIL_BLOB = (
    "https://warsydprdstafuelwatch.blob.core.windows.net/"
    "historical-reports/FuelWatchRetail-{month:02d}-{year}.csv"
)
WHOLESALE_BLOB = (
    "https://warsydprdstafuelwatch.blob.core.windows.net/"
    "historical-reports/FuelWatchWholesale-{year}.csv"
)
FRED_BRENT_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
DAILY_FEED_URL = FUELWATCH_API + "/sites?fuelType=ULP"

USER_AGENT = "fuel-shock-radar/1.0 (portfolio research; CC BY attribution)"

TANK_LITRES = 55.0
CYCLE_WEEKS = 16
REGION_DAYS = 28
MARGIN_DAYS = 7

# Status colours are decided only from these cut-offs.
# Spread and gap are cents per litre. Savings are Australian dollars.
SPREAD_HIGH = 12.0
SPREAD_ELEVATED = 6.0
SAVINGS_HIGH = 8.0
SAVINGS_ELEVATED = 4.0
# Margin status is relative to the past year of daily gaps.
MARGIN_HIGH_ABOVE_MEDIAN = 4.0
MARGIN_ELEVATED_ABOVE_MEDIAN = 1.5
GAP_HIGH = 25.0
GAP_ELEVATED = 12.0

PRODUCTS = ("ULP", "Diesel", "Brand Diesel")
FOCUS_PRODUCT = "ULP"
PERTH_TERMINAL_TOKENS = ("KWINANA", "KEWDALE")

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Cited, not computed. ABS Consumer Price Index, Australia, September 2026.
CPI_TRANSPORT_YOY = 8.7
CPI_FUEL_YOY = 23.6
CPI_HEADLINE_YOY = 4.3
CPI_PERIOD = "the year to September 2026"
CPI_SOURCE = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release"
