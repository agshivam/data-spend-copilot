"""Data Spend Copilot - MCP server.

Lets any MCP client (Claude Desktop, Cursor, an internal agent) answer questions
like "why did Aurora's spend jump in May?" or "what will Cascade spend next year
if AI usage doubles?" - using governed semantic-layer metrics, never raw SQL.

Access control: set COPILOT_CLIENT_SCOPE=<client_id> to lock the server to one
client (e.g. when you hand it to that client). Every tool then forces that
filter, whatever the agent asks for.

Run:  python -m mcp_server.server        (stdio transport)
"""

from __future__ import annotations

import functools
import os
from datetime import date

import pandas as pd
try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

from copilot import forecast as fc
from copilot import semantic, warehouse

mcp = FastMCP("data-spend-copilot")
SCOPE = os.environ.get("COPILOT_CLIENT_SCOPE") or None


def tool(fn):
    """Register an MCP tool; expected errors go back to the agent as readable messages."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (semantic.QueryError, PermissionError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
    return mcp.tool()(wrapper)


def _scoped(client_id: str | None) -> str | None:
    """Apply the server's client scope; refuse cross-client requests."""
    if SCOPE:
        if client_id and client_id != SCOPE:
            raise PermissionError(f"This server is scoped to client '{SCOPE}'.")
        return SCOPE
    return client_id


def _records(df: pd.DataFrame, max_rows: int = 200) -> list[dict]:
    df = df.head(max_rows).copy()
    for col in df.select_dtypes("number"):
        df[col] = df[col].round(4)
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@tool
def list_metrics() -> list[dict]:
    """List the governed spend metrics (name, label, definition) available to query."""
    return semantic.list_metrics()


@tool
def list_clients() -> list[dict]:
    """List client accounts this server can see."""
    df = warehouse.clients()
    if SCOPE:
        df = df[df["client_id"] == SCOPE]
    return _records(df)


@tool
def query_spend(
    metrics: list[str],
    grain: str = "month",
    group_by: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    client_id: str | None = None,
) -> list[dict]:
    """Query spend metrics through the semantic layer.

    metrics: e.g. ["total_spend"], ["ai_spend", "ai_share_of_spend"]. See list_metrics.
    grain: day | week | month | quarter | year.
    group_by: any of client, client_id, industry, platform, category, sub_category.
    start_date / end_date: YYYY-MM-DD (inclusive).
    client_id: restrict to one client (e.g. "c_aurora").
    """
    df = semantic.query(metrics, grain=grain, group_by=group_by, start_date=start_date,
                        end_date=end_date, client_id=_scoped(client_id))
    return _records(df)


@tool
def explain_month_change(client_id: str, month: str) -> dict:
    """Explain what drove a client's spend change in a month vs the month before.

    month: YYYY-MM. Returns total change and the biggest movers by line item.
    """
    client_id = _scoped(client_id)
    current = pd.Period(month, freq="M")
    previous = current - 1
    df = semantic.query(["total_spend"], grain="month", group_by=["category", "sub_category"],
                        start_date=str(previous.start_time.date()), end_date=str(current.end_time.date()),
                        client_id=client_id)
    df["period"] = pd.to_datetime(df["period"]).dt.to_period("M")
    pivot = df.pivot_table(index=["category", "sub_category"], columns="period",
                           values="total_spend", aggfunc="sum").fillna(0.0)
    for p in (previous, current):
        if p not in pivot.columns:
            pivot[p] = 0.0
    pivot["change_usd"] = pivot[current] - pivot[previous]
    movers = pivot.sort_values("change_usd", key=abs, ascending=False).head(8).reset_index()
    movers = movers.rename(columns={previous: "previous_usd", current: "current_usd"})
    return {
        "client_id": client_id,
        "month": month,
        "previous_month_total_usd": round(float(pivot[previous].sum()), 2),
        "month_total_usd": round(float(pivot[current].sum()), 2),
        "change_usd": round(float(pivot["change_usd"].sum()), 2),
        "top_movers": _records(movers[["category", "sub_category", "previous_usd", "current_usd", "change_usd"]]),
    }


@tool
def list_anomalies(since: str = "2026-01-01", client_id: str | None = None) -> list[dict]:
    """Days where spend jumped far above its 28-day baseline (possible incidents)."""
    date.fromisoformat(since)
    return _records(warehouse.anomalies(since, _scoped(client_id)))


@tool
def top_dbt_models_by_cost(client_id: str, since: str = "2026-10-01", limit: int = 10) -> list[dict]:
    """Most expensive dbt models for a client since a date (cost attributed from warehouse credits)."""
    date.fromisoformat(since)
    return _records(warehouse.top_dbt_models(_scoped(client_id), since, min(int(limit), 50)))


@tool
def forecast_next_12_months(
    client_id: str,
    compute_growth_adj_pct: float = 0.0,
    ai_multiplier: float = 1.0,
    ingestion_growth_adj_pct: float = 0.0,
    storage_growth_adj_pct: float = 0.0,
) -> dict:
    """Forecast a client's next-12-month spend, with optional what-if levers.

    compute_growth_adj_pct: +10 means 10% more compute than trend by month 12.
    ai_multiplier: 2.0 means AI usage doubles vs trend by month 12.
    ingestion_growth_adj_pct: +25 for new Fivetran connectors adding 25% rows.
    """
    scenario = fc.Scenario(compute_growth_adj_pct, ai_multiplier, ingestion_growth_adj_pct, storage_growth_adj_pct)
    result = fc.forecast(_scoped(client_id), scenario)
    return {
        "client_id": result["client_id"],
        "last_12m_total_usd": result["last_12m_total_usd"],
        "next_12m_total_usd": result["next_12m_total_usd"],
        "next_12m_range_usd": [result["next_12m_low_usd"], result["next_12m_high_usd"]],
        "monthly_growth_pct_by_series": {k: float(v) for k, v in result["monthly_growth_pct_by_series"].items()},
        "scenario": result["scenario"],
        "forecast_by_month": _records(result["forecast_by_month"]),
    }


if __name__ == "__main__":
    mcp.run()
