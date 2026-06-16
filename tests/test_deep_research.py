"""Tests for deep_research module — pure functions only.

Run: pytest tests/test_deep_research.py -v
"""

import pytest

from deep_research.valuation import (
    _dcf_value_per_share,
    _unwrap as val_unwrap,
    _safe_float as val_safe_float,
    _get as val_get,
    _series as val_series,
    _market_info,
    _current_price,
    _shares_outstanding,
)
from deep_research.risk_flags import (
    _consecutive_declines,
    _growth_pct,
    _flag,
)
from deep_research.governance import (
    _trend,
    _unwrap as gov_unwrap,
    _safe_float as gov_safe_float,
    _series as gov_series,
)
from deep_research.screener_client import (
    _clean_symbol,
    _strip_tags,
    _to_number,
    _growth_from_series,
)


# ═══════════════════════════════════════════════════════════════
# valuation.py
# ═══════════════════════════════════════════════════════════════

# ── _dcf_value_per_share ──
def test_dcf_basic():
    val = _dcf_value_per_share(fcf=1000, shares=100, growth=0.10, wacc=0.12, terminal_growth=0.04)
    assert val is not None
    assert val > 0


def test_dcf_negative_fcf_returns_none():
    assert _dcf_value_per_share(fcf=-100, shares=100, growth=0.10, wacc=0.12, terminal_growth=0.04) is None


def test_dcf_zero_shares_returns_none():
    assert _dcf_value_per_share(fcf=1000, shares=0, growth=0.10, wacc=0.12, terminal_growth=0.04) is None


def test_dcf_wacc_le_terminal_growth_returns_none():
    """WACC <= terminal growth makes terminal value negative/infinite."""
    assert _dcf_value_per_share(fcf=1000, shares=100, growth=0.10, wacc=0.03, terminal_growth=0.04) is None


def test_dcf_higher_growth_gives_higher_value():
    val_low = _dcf_value_per_share(fcf=1000, shares=100, growth=0.05, wacc=0.12, terminal_growth=0.04)
    val_high = _dcf_value_per_share(fcf=1000, shares=100, growth=0.15, wacc=0.12, terminal_growth=0.04)
    assert val_high > val_low


def test_dcf_higher_wacc_gives_lower_value():
    val_low = _dcf_value_per_share(fcf=1000, shares=100, growth=0.10, wacc=0.08, terminal_growth=0.04)
    val_high = _dcf_value_per_share(fcf=1000, shares=100, growth=0.10, wacc=0.15, terminal_growth=0.04)
    assert val_high < val_low


# ── _unwrap ──
def test_val_unwrap_dict_with_data():
    assert val_unwrap({"data": {"key": "val"}}) == {"key": "val"}


def test_val_unwrap_plain_dict():
    assert val_unwrap({"key": "val"}) == {"key": "val"}


def test_val_unwrap_none():
    assert val_unwrap(None) == {}


def test_val_unwrap_string():
    assert val_unwrap("not_a_dict") == {}


# ── _safe_float ──
def test_val_safe_float_int():
    assert val_safe_float(42) == 42.0


def test_val_safe_float_str_with_comma():
    assert val_safe_float("1,234.56") == 1234.56


def test_val_safe_float_str_with_percent():
    assert val_safe_float("15.5%") == 15.5


def test_val_safe_float_none():
    assert val_safe_float(None) is None


def test_val_safe_float_garbage():
    assert val_safe_float("not a number") is None


# ── _get (deep dict access) ──
def test_val_get_nested():
    d = {"a": {"b": {"c": 42}}}
    assert val_get(d, ["a", "b", "c"]) == 42


def test_val_get_missing():
    d = {"a": {"b": 1}}
    assert val_get(d, ["a", "x"], "default") == "default"


def test_val_get_not_a_dict():
    assert val_get(42, ["a", "b"], "fallback") == "fallback"


def test_val_get_none_value_returns_default():
    """When key exists but value is None, returns default."""
    d = {"a": None}
    assert val_get(d, ["a"], "default") == "default"


# ── _series ──
def test_val_series():
    d = {"pl": {"sales": ["100", "200", "300"]}}
    assert val_series(d, ["pl", "sales"]) == [100.0, 200.0, 300.0]


def test_val_series_missing():
    assert val_series({}, ["pl", "sales"]) == []


def test_val_series_with_nulls():
    d = {"pl": {"sales": ["100", None, "300", "bad"]}}
    assert val_series(d, ["pl", "sales"]) == [100.0, 300.0]


# ── _market_info ──
def test_market_info_fundamentals_first():
    d = {"fundamentals": {"pe": 15}, "info": {"pe": 20}}
    assert _market_info(d) == {"pe": 15}


def test_market_info_falls_back_to_info():
    d = {"info": {"pe": 20}}
    assert _market_info(d) == {"pe": 20}


def test_market_info_falls_back_to_self():
    d = {"price": 100}
    assert _market_info(d) == {"price": 100}


# ── _current_price ──
def test_current_price_from_market_data():
    md = {"price": 150.0}
    assert _current_price(md, {}) == 150.0


def test_current_price_from_info():
    md = {"info": {"currentPrice": 200.0}}
    assert _current_price(md, {}) == 200.0


def test_current_price_from_financials():
    fin = {"ratios": {"current_price": 175.5}}
    assert _current_price({}, fin) == 175.5


def test_current_price_missing():
    assert _current_price({}, {}) is None


# ── _shares_outstanding ──
def test_shares_from_info():
    md = {"info": {"sharesOutstanding": 1_000_000}}
    assert _shares_outstanding(md, 100) == 1_000_000


def test_shares_from_market_cap():
    md = {"info": {"marketCap": 10_000_000}}
    assert _shares_outstanding(md, 100) == 100_000


def test_shares_missing():
    assert _shares_outstanding({}, None) is None


# ═══════════════════════════════════════════════════════════════
# risk_flags.py
# ═══════════════════════════════════════════════════════════════

# ── _consecutive_declines ──
def test_consecutive_declines_true():
    assert _consecutive_declines([100, 90, 80, 70], 3) is True


def test_consecutive_declines_false():
    assert _consecutive_declines([100, 90, 95, 70], 3) is False


def test_consecutive_declines_too_short():
    assert _consecutive_declines([100, 90], 3) is None


def test_consecutive_declines_flat():
    assert _consecutive_declines([100, 100, 100, 100], 3) is False


# ── _growth_pct ──
def test_growth_pct_positive():
    assert _growth_pct(100, 120) == 20.0


def test_growth_pct_negative():
    assert _growth_pct(100, 80) == -20.0


def test_growth_pct_zero_start():
    assert _growth_pct(0, 100) is None


def test_growth_pct_none_end():
    assert _growth_pct(100, None) is None


# ── _flag ──
def test_flag_triggered():
    f = _flag("Test flag", True, "evidence here", "explanation", "high")
    assert f["status"] == "triggered"
    assert f["severity"] == "high"
    assert f["name"] == "Test flag"


def test_flag_clear():
    f = _flag("Test", False, "ok", "explanation", "medium")
    assert f["status"] == "clear"
    assert f["severity"] == "none"


def test_flag_unchecked():
    f = _flag("Test", None, "", "explanation")
    assert f["status"] == "unchecked"
    assert f["severity"] == "unknown"


# ═══════════════════════════════════════════════════════════════
# governance.py
# ═══════════════════════════════════════════════════════════════

# ── _trend ──
def test_trend_increasing():
    assert _trend([10, 12, 15]) == "increasing"


def test_trend_decreasing():
    assert _trend([20, 15, 10]) == "decreasing"


def test_trend_stable():
    assert _trend([10.1, 10.2, 10.0]) == "stable"


def test_trend_unavailable():
    assert _trend([42]) == "unavailable"
    assert _trend([]) == "unavailable"


def test_trend_custom_tolerance():
    assert _trend([10, 12], tolerance=3.0) == "stable"


# ── _unwrap ──
def test_gov_unwrap():
    assert gov_unwrap({"data": {"x": 1}}) == {"x": 1}
    assert gov_unwrap(None) == {}


# ── _safe_float ──
def test_gov_safe_float():
    assert gov_safe_float("3.14") == 3.14
    assert gov_safe_float(None) is None


# ── _series ──
def test_gov_series():
    d = {"sh": {"promoter": [51.0, 50.5, 49.0]}}
    assert gov_series(d, ["sh", "promoter"]) == [51.0, 50.5, 49.0]


# ═══════════════════════════════════════════════════════════════
# screener_client.py
# ═══════════════════════════════════════════════════════════════

# ── _clean_symbol ──
def test_clean_symbol_ns():
    assert _clean_symbol("SBIN.NS") == "SBIN"


def test_clean_symbol_bo():
    assert _clean_symbol("TCS.BO") == "TCS"


def test_clean_symbol_plain():
    assert _clean_symbol("RELIANCE") == "RELIANCE"


def test_clean_symbol_lowercase():
    assert _clean_symbol("infy.ns") == "INFY"


def test_clean_symbol_special_chars():
    assert _clean_symbol("M&M") == "M&M"


# ── _strip_tags ──
def test_strip_tags_simple():
    assert _strip_tags("<b>Hello</b> World") == "Hello World"


def test_strip_tags_script():
    assert _strip_tags("<script>alert(1)</script>text") == "text"


def test_strip_tags_html_entities():
    result = _strip_tags("Profit &amp; Loss")
    assert "Profit" in result
    assert "Loss" in result


def test_strip_tags_empty():
    assert _strip_tags("") == ""


# ── _to_number ──
@pytest.mark.parametrize("inp,expected", [
    ("1,234.56", 1234.56),
    ("15.5%", 15.5),
    ("₹ 942,308 Cr.", 942308),
    ("-", None),
    ("NA", None),
    ("--", None),
    (None, None),
    (42, 42.0),
])
def test_to_number(inp, expected):
    result = _to_number(inp)
    if expected is None:
        assert result is None
    else:
        assert result == expected


def test_to_number_negative_brackets():
    """Screener shows negative numbers in brackets like (123)."""
    assert _to_number("(123.45)") == -123.45


def test_to_number_lakh_conversion():
    """Lakh values should be converted to crore scale (/100)."""
    val = _to_number("500 L")
    assert val == 5.0


# ── _growth_from_series ──
def test_growth_from_series_3yr():
    values = [100, 110, 120, 130, 150]
    g = _growth_from_series(values, 3)
    assert g is not None
    # (150/120)^(1/3)-1 ≈ 7.7%
    assert 5 < g < 12


def test_growth_from_series_too_short():
    assert _growth_from_series([100, 110], 3) is None


def test_growth_from_series_with_nones():
    values = [100, None, 120, None, 140, 160]
    # Cleaned: [100, 120, 140, 160]. 3yr from 100 to 160
    g = _growth_from_series(values, 3)
    assert g is not None
    assert 14 < g < 22  # ~17%


def test_growth_from_series_negative():
    values = [-100, -90, -80]
    assert _growth_from_series(values, 2) is None  # negative start
