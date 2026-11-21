"""Next-12-month spend forecast with explainable what-if levers.

Method (deliberately simple so a client can follow it):
  1. Monthly spend per category from the semantic layer.
  2. Growth rate per category = MEDIAN month-over-month growth over the last 6
     complete months (a one-off spike can't distort it), clipped to -5%..+6%.
  3. Project 12 months forward, then apply the scenario levers.
  4. Low/high range = re-run using the 25th / 75th percentile monthly growth.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from copilot import semantic

CATEGORY_METRICS = {
    "compute": "compute_spend",
    "ai": "ai_spend",
    "ingestion": "ingestion_spend",
    "storage": "storage_spend",
}


@dataclass
class Scenario:
    compute_growth_adj_pct: float = 0.0    # e.g. +10 -> 10% more compute than trend by month 12
    ai_multiplier: float = 1.0             # e.g. 2.0 -> AI usage doubles vs trend
    ingestion_growth_adj_pct: float = 0.0  # e.g. +25 -> new connectors add 25% MAR
    storage_growth_adj_pct: float = 0.0


def _monthly_history(client_id: str) -> pd.DataFrame:
    metrics = list(CATEGORY_METRICS.values()) + ["total_spend"]
    df = semantic.query(metrics, grain="month", client_id=client_id).set_index("period").fillna(0.0)
    df["other_snowflake"] = df["total_spend"] - df[list(CATEGORY_METRICS.values())].sum(axis=1)
    return df.drop(columns="total_spend")


def forecast(client_id: str, scenario: Scenario | None = None, lookback: int = 6) -> dict:
    scenario = scenario or Scenario()
    hist = _monthly_history(client_id)
    in_progress = pd.Timestamp(hist.index[-1]).to_period("M") == pd.Timestamp.today().to_period("M")
    complete = hist.iloc[:-1] if in_progress else hist  # never extrapolate a half-finished month
    recent = complete.tail(lookback)

    last_month = pd.Timestamp(complete.index[-1])
    future = [(last_month + pd.DateOffset(months=i)).date() for i in range(1, 13)]
    levers = {
        "compute_spend": 1 + scenario.compute_growth_adj_pct / 100,
        "ai_spend": scenario.ai_multiplier,
        "ingestion_spend": 1 + scenario.ingestion_growth_adj_pct / 100,
        "storage_spend": 1 + scenario.storage_growth_adj_pct / 100,
        "other_snowflake": 1.0,
    }

    rows, growth_rates = [], {}
    low_total = high_total = 0.0
    clip = lambda s: float(np.clip(s, np.log(0.95), np.log(1.06)))  # -5% .. +6% per month
    for col in recent.columns:
        y = recent[col].clip(lower=1e-6).to_numpy()
        mom = np.diff(np.log(y))  # month-over-month log growth
        slope, slope_low, slope_high = (float(np.percentile(mom, q)) for q in (50, 25, 75))
        growth_rates[col] = round(float(np.exp(clip(slope)) - 1) * 100, 2)
        base = float(y[-1])
        for i, month in enumerate(future, start=1):
            ramp = 1 + (levers[col] - 1) * (i / 12)  # levers phase in over the year
            rows.append({"period": month, "series": col, "cost_usd": base * np.exp(clip(slope) * i) * ramp})
            low_total += base * np.exp(clip(slope_low) * i) * ramp
            high_total += base * np.exp(clip(slope_high) * i) * ramp

    fc = pd.DataFrame(rows)
    by_month = fc.pivot_table(index="period", columns="series", values="cost_usd", aggfunc="sum")
    total = by_month.sum(axis=1)
    last_12 = complete.tail(12).sum().sum()

    return {
        "client_id": client_id,
        "history": complete.reset_index(),
        "forecast_by_month": by_month.reset_index(),
        "monthly_growth_pct_by_series": growth_rates,
        "next_12m_total_usd": round(float(total.sum()), 0),
        "next_12m_low_usd": round(low_total, 0),
        "next_12m_high_usd": round(high_total, 0),
        "last_12m_total_usd": round(float(last_12), 0),
        "scenario": scenario.__dict__,
    }
