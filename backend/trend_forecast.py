"""
PREDICTA – Trend Forecast Engine (shared by Segment A and Segment B)
Answers "if the current trend continues, how long until each variable reaches
its warning / critical limit?" using a linear fit over recent running data.

This is an extrapolation of the present trend, not a guarantee: it assumes the
load profile and the rate of degradation stay the same. Forecasts are only
reported when the trend is statistically significant and only up to a horizon
of a few times the observed window, beyond which extrapolation is not credible.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List

from analytics_engine import TREND_VARIABLES, running_rows

MIN_POINTS = 12
MIN_R2 = 0.3
HORIZON_MULTIPLIER = 5.0           # forecast no further than 5x the fitted window span
MAX_HORIZON_HOURS = 24.0 * 30      # and never beyond 30 days


def _limit_targets(cfg: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Normalise the different limit styles used in DEFAULT_ENGINEERING_LIMITS."""
    return {
        "upper_warn": cfg.get("warn", cfg.get("max_warn")),
        "upper_crit": cfg.get("crit", cfg.get("max_crit")),
        "lower_warn": cfg.get("min_warn"),
        "lower_crit": cfg.get("min_crit"),
    }


def _hours_to(limit: Optional[float], level: float, slope: float, slope_se: float) -> Optional[Dict[str, Any]]:
    """Hours until `level` reaches `limit` at `slope`, with a 95% interval from the slope error."""
    if limit is None or slope == 0:
        return None
    gap = limit - level
    if gap * slope <= 0:            # moving away from this limit
        return None
    hours = gap / slope
    fast = abs(slope) + 1.96 * slope_se
    slow = abs(slope) - 1.96 * slope_se
    return {
        "hours": round(float(hours), 2),
        "ci_hours": [round(float(abs(gap) / fast), 2), round(float(abs(gap) / slow), 2) if slow > 0 else None],
    }


def _fit_variable(times_h: np.ndarray, values: np.ndarray) -> Dict[str, float]:
    x = times_h - times_h[0]
    slope, intercept = np.polyfit(x, values, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((values - fitted) ** 2))
    ss_tot = float(np.sum((values - values.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    sxx = float(np.sum((x - x.mean()) ** 2))
    slope_se = float(np.sqrt(ss_res / max(1, len(x) - 2) / sxx)) if sxx > 0 else float("inf")
    return {
        "slope": float(slope),
        "slope_se": slope_se,
        "r2": max(0.0, r2),
        "level": float(fitted[-1]),
        "span_hours": float(x[-1]),
    }


def forecast_time_to_limits(
    df: pd.DataFrame,
    limits: Dict[str, Dict[str, Any]],
    timestamp_col: Optional[str] = None,
    recent_fraction: float = 0.3,
    max_points: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fits a linear trend to the most recent running data of every limited variable
    and estimates the time to its warning and critical limits.

    df must contain `_std_<variable>` columns and a timestamp column.
    Returns per-variable results plus the earliest critical / warning crossing.
    """
    if not timestamp_col or timestamp_col not in df.columns:
        return {
            "available": False,
            "reason": "Trend forecast needs a timestamp column to express time-to-limit in hours.",
            "variables": [],
        }

    data = running_rows(df).copy()
    data["_forecast_ts"] = pd.to_datetime(data[timestamp_col], errors="coerce")
    data = data.dropna(subset=["_forecast_ts"]).sort_values("_forecast_ts")

    results: List[Dict[str, Any]] = []
    for var in TREND_VARIABLES:
        col = f"_std_{var}"
        if col not in data.columns or var not in limits:
            continue
        cfg = limits[var]
        targets = _limit_targets(cfg)
        series = data[["_forecast_ts", col]].dropna()
        entry: Dict[str, Any] = {
            "variable": var,
            "unit": cfg.get("unit", ""),
            "warning_limit": targets["upper_warn"] if targets["upper_warn"] is not None else targets["lower_warn"],
            "critical_limit": targets["upper_crit"] if targets["upper_crit"] is not None else targets["lower_crit"],
        }

        window = max(MIN_POINTS, int(len(series) * recent_fraction))
        if max_points:
            window = min(window, max_points)
        recent = series.tail(window)
        if len(recent) < MIN_POINTS:
            entry.update({"status": "INSUFFICIENT_DATA", "window_points": int(len(recent))})
            results.append(entry)
            continue

        t0 = recent["_forecast_ts"].iloc[0]
        times_h = ((recent["_forecast_ts"] - t0).dt.total_seconds() / 3600.0).to_numpy()
        values = pd.to_numeric(recent[col], errors="coerce").to_numpy(dtype=float)
        if times_h[-1] <= 0:
            entry.update({"status": "INSUFFICIENT_DATA", "window_points": int(len(recent))})
            results.append(entry)
            continue

        fit = _fit_variable(times_h, values)
        level, slope, slope_se = fit["level"], fit["slope"], fit["slope_se"]
        if slope < 0 and (targets["lower_crit"] is not None or targets["lower_warn"] is not None):
            entry["warning_limit"], entry["critical_limit"] = targets["lower_warn"], targets["lower_crit"]
        horizon = min(MAX_HORIZON_HOURS, HORIZON_MULTIPLIER * fit["span_hours"])
        significant = fit["r2"] >= MIN_R2 and abs(slope) > 2 * slope_se

        entry.update({
            "latest_value": round(float(values[-1]), 3),
            "trend_level": round(level, 3),
            "slope_per_hour": round(slope, 4),
            "r2": round(fit["r2"], 3),
            "window_points": int(len(recent)),
            "window_hours": round(fit["span_hours"], 2),
            "forecast_horizon_hours": round(horizon, 2),
            "direction": ("RISING" if slope > 0 else "FALLING") if significant else "STABLE",
            "hours_to_warning": None,
            "hours_to_critical": None,
            "hours_to_critical_ci": None,
        })

        above_crit = targets["upper_crit"] is not None and level >= targets["upper_crit"]
        below_crit = targets["lower_crit"] is not None and level <= targets["lower_crit"]
        above_warn = targets["upper_warn"] is not None and level >= targets["upper_warn"]
        below_warn = targets["lower_warn"] is not None and level <= targets["lower_warn"]

        if above_crit or below_crit:
            entry.update({"status": "CRITICAL_LIMIT_EXCEEDED", "hours_to_critical": 0.0, "hours_to_warning": 0.0})
            results.append(entry)
            continue

        if significant:
            crit_limit = targets["upper_crit"] if slope > 0 else targets["lower_crit"]
            warn_limit = targets["upper_warn"] if slope > 0 else targets["lower_warn"]
            to_crit = _hours_to(crit_limit, level, slope, slope_se)
            to_warn = None if (above_warn or below_warn) else _hours_to(warn_limit, level, slope, slope_se)
            if to_crit and to_crit["hours"] <= horizon:
                entry["hours_to_critical"] = to_crit["hours"]
                entry["hours_to_critical_ci"] = to_crit["ci_hours"]
            if to_warn and to_warn["hours"] <= horizon:
                entry["hours_to_warning"] = to_warn["hours"]
            if above_warn or below_warn:
                entry["hours_to_warning"] = 0.0

        if above_warn or below_warn:
            entry["status"] = "WARNING_LIMIT_EXCEEDED"
        elif entry["hours_to_critical"] is not None or entry["hours_to_warning"] is not None:
            entry["status"] = "APPROACHING_LIMIT"
        elif significant:
            entry["status"] = "DRIFTING"
        else:
            entry["status"] = "STABLE"
        results.append(entry)

    def _earliest(key: str) -> Optional[Dict[str, Any]]:
        candidates = [r for r in results if r.get(key) is not None]
        if not candidates:
            return None
        best = min(candidates, key=lambda r: r[key])
        return {
            "variable": best["variable"],
            "hours": best[key],
            "ci_hours": best.get("hours_to_critical_ci") if key == "hours_to_critical" else None,
            "limit": best["critical_limit"] if key == "hours_to_critical" else best["warning_limit"],
            "unit": best["unit"],
        }

    evaluated = [r for r in results if r.get("status") != "INSUFFICIENT_DATA"]
    return {
        "available": bool(evaluated),
        "reason": None if evaluated else "Not enough recent running data with timestamps to fit a trend.",
        "method": "Linear least-squares trend over the most recent running data, extrapolated to engineering limits",
        "assumptions": "Assumes the current load profile and rate of change continue. "
                       "Not a validated remaining-useful-life estimate.",
        "earliest_critical": _earliest("hours_to_critical"),
        "earliest_warning": _earliest("hours_to_warning"),
        "variables": results,
    }


def trend_risk_score(forecast: Dict[str, Any]) -> Optional[float]:
    """
    0–100 trend deterioration score for Layer 5.
    Returns None when no forecast could be made, so Layer 5 keeps its original weights.
    """
    if not forecast or not forecast.get("available"):
        return None
    score = 0.0
    for v in forecast.get("variables", []):
        status = v.get("status")
        horizon = v.get("forecast_horizon_hours") or 1.0
        if status == "CRITICAL_LIMIT_EXCEEDED":
            score = max(score, 100.0)
        elif v.get("hours_to_critical") is not None:
            score = max(score, 40.0 + 50.0 * (1.0 - min(1.0, v["hours_to_critical"] / horizon)))
        elif status == "WARNING_LIMIT_EXCEEDED":
            score = max(score, 50.0)
        elif v.get("hours_to_warning") is not None:
            score = max(score, 20.0 + 25.0 * (1.0 - min(1.0, v["hours_to_warning"] / horizon)))
        elif status == "DRIFTING":
            score = max(score, 10.0)
    return round(score, 1)
