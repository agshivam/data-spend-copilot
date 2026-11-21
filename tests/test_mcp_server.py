"""End-to-end tests: start the MCP server over stdio and call its tools like an agent would.

Requires the data + dbt build to have run first (see HOW_TO_RUN.md / CI).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def _call(tool: str, args: dict, scope: str | None = None):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    if scope:
        env["COPILOT_CLIENT_SCOPE"] = scope
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            return getattr(result, "is_error", getattr(result, "isError", False)), text


def call(tool, args, scope=None):
    return asyncio.run(_call(tool, args, scope))


def test_lists_governed_metrics():
    is_error, text = call("list_metrics", {})
    assert not is_error and "ai_spend" in text and "ai_share_of_spend" in text


def test_query_spend_by_client():
    is_error, text = call("query_spend", {"metrics": ["total_spend"], "grain": "year", "group_by": ["client"]})
    assert not is_error and "Aurora Retail Co" in text


def test_explains_fivetran_resync_spike():
    is_error, text = call("explain_month_change", {"client_id": "c_aurora", "month": "2026-05"})
    assert not is_error
    data = json.loads(text)
    assert data["top_movers"][0]["sub_category"] == "salesforce_prod"


def test_finds_weekend_warehouse_incident():
    is_error, text = call("list_anomalies", {"since": "2026-08-01", "client_id": "c_borealis"})
    assert not is_error and "2026-08-14" in text


def test_forecast_what_if_raises_total():
    _, base = call("forecast_next_12_months", {"client_id": "c_cascade"})
    _, more_ai = call("forecast_next_12_months", {"client_id": "c_cascade", "ai_multiplier": 2.0})
    assert json.loads(more_ai)["next_12m_total_usd"] > json.loads(base)["next_12m_total_usd"]


def test_scope_blocks_other_clients():
    is_error, text = call("query_spend", {"metrics": ["total_spend"], "client_id": "c_aurora"}, scope="c_cascade")
    assert is_error and "scoped" in text


@pytest.mark.parametrize("bad", [["total_spend; drop table x"], ["not_a_metric"]])
def test_rejects_unknown_metrics(bad):
    is_error, text = call("query_spend", {"metrics": bad})
    assert is_error and "Unknown metric" in text
