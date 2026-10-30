import pandas as pd

from fuel_shock.quality import validate


def _frames():
    return {
        "retail": pd.DataFrame(
            {
                "publish_date": ["2026-10-01", "2026-10-02"],
                "station_key": ["a|perth|6000", "b|bunbury|6230"],
                "price_cpl": [180.0, 210.0],
                "product": ["ULP", "ULP"],
                "region": ["Metro", "South-West"],
            }
        ),
        "wholesale": pd.DataFrame(
            {
                "publish_date": ["2026-10-01"],
                "terminal": ["Ampol Kwinana"],
                "price_cpl": [160.0],
                "product": ["ULP"],
            }
        ),
        "brent": pd.DataFrame(
            {"observe_date": ["2026-10-01", "2026-10-02"], "brent_usd": [80.0, 82.5]}
        ),
    }


def test_expectations_pass_and_data_docs_are_written(tmp_path):
    result = validate(_frames(), tmp_path)
    assert result["success"] is True
    assert (tmp_path / "index.html").exists()
    assert "retail_prices" in (tmp_path / "index.html").read_text() or (
        tmp_path / "_gx_project" / "gx" / "uncommitted" / "data_docs" / "local_site" / "index.html"
    ).exists()


def test_expectations_fail_on_a_price_outside_the_band(tmp_path):
    frames = _frames()
    frames["retail"].loc[0, "price_cpl"] = 900
    result = validate(frames, tmp_path)
    assert result["success"] is False
    assert result["suites"]["retail"]["success"] is False
