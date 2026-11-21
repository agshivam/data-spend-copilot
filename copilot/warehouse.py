"""Read-only access to mart tables that are not metrics (anomalies, dbt model costs).

Works against DuckDB (default) or Snowflake (DBT_TARGET=snowflake). Only fixed,
parameterised queries are exposed - no free-form SQL from users or agents.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

ANOMALIES_SQL = """
select client_id, spend_date, category, cost_usd, baseline_usd, z_score, excess_usd
from marts.fct_spend_anomalies
where spend_date >= ? {client_filter}
order by excess_usd desc
limit 50
"""

DBT_COST_SQL = """
select model_name, sum(runs) as runs, round(avg(avg_execution_seconds), 1) as avg_seconds,
       round(sum(cost_usd), 2) as cost_usd
from marts.fct_dbt_model_cost
where client_id = ? and spend_month >= ?
group by model_name
order by cost_usd desc
limit ?
"""


def _run(sql: str, params: list) -> pd.DataFrame:
    if os.environ.get("DBT_TARGET") == "snowflake":
        import snowflake.connector  # optional dependency

        con = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"], role=os.environ.get("SNOWFLAKE_ROLE"),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
            database=os.environ.get("SNOWFLAKE_DATABASE", "SPEND_COPILOT"),
            paramstyle="qmark",
        )
        try:
            return con.cursor().execute(sql, params).fetch_pandas_all()
        finally:
            con.close()

    import duckdb

    db = os.environ.get("SPEND_DB", str(ROOT / "data" / "spend.duckdb"))
    with duckdb.connect(db, read_only=True) as con:
        return con.execute(sql, params).df()


def anomalies(since: str, client_id: str | None = None) -> pd.DataFrame:
    if client_id:
        return _run(ANOMALIES_SQL.format(client_filter="and client_id = ?"), [since, client_id])
    return _run(ANOMALIES_SQL.format(client_filter=""), [since])


def top_dbt_models(client_id: str, since: str, limit: int = 10) -> pd.DataFrame:
    return _run(DBT_COST_SQL, [client_id, since, int(limit)])


def clients() -> pd.DataFrame:
    return _run("select client_id, client_name, industry from marts.dim_clients order by client_name", [])
