"""Generate realistic, fully synthetic spend data for 3 fictional clients.

The raw tables mirror the shape of the real sources, so the same dbt models
run on real data with the extraction SQL in sql/snowflake/:
  - SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY   -> raw.warehouse_metering
  - SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY -> raw.storage_usage
  - SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY       -> raw.serverless_metering
  - SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY -> raw.cortex_usage
  - FIVETRAN_METADATA.INCREMENTAL_MAR                    -> raw.fivetran_mar
  - dbt run results (query tags / artifacts)             -> raw.dbt_runs

Story baked into the data (so the dashboard and the agent have something to find):
  * steady business growth with weekday seasonality
  * Cortex AI adoption ramps up from early 2026 and becomes a real cost line
  * a Fivetran historical re-sync spike for one client (schema change)
  * a warehouse left running over a long weekend for another client
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SEED = 42
END = date(2026, 10, 31)
DAYS = 730

CLIENTS = [
    # client_id, name, industry, $/credit, $/TB-month, $/million paid MAR, size factor
    ("c_aurora", "Aurora Retail Co", "Retail", 3.00, 23.0, 450.0, 1.6),
    ("c_borealis", "Borealis Logistics", "Logistics", 2.70, 23.0, 500.0, 1.0),
    ("c_cascade", "Cascade Fintech", "Financial services", 3.30, 40.0, 420.0, 0.7),
]

WAREHOUSES = {
    "LOAD_WH": 6.0,       # base daily credits before size factor
    "TRANSFORM_WH": 14.0,
    "BI_WH": 9.0,
    "ADHOC_WH": 4.0,
}

SERVERLESS = {
    "SNOWPIPE": 0.8,
    "AUTO_CLUSTERING": 1.2,
    "MATERIALIZED_VIEW": 0.5,
    "SERVERLESS_TASK": 0.6,
    "SEARCH_OPTIMIZATION": 0.3,
}

CORTEX = [
    # function, model, credits per million tokens, base daily tokens at full adoption
    ("COMPLETE", "claude-sonnet", 2.55, 9_000_000),
    ("COMPLETE", "llama3.1-70b", 1.21, 6_000_000),
    ("EMBED_TEXT_768", "snowflake-arctic-embed-m", 0.03, 40_000_000),
    ("AI_CLASSIFY", "default", 1.39, 4_000_000),
    ("SUMMARIZE", "default", 0.10, 8_000_000),
]

CONNECTORS = {
    # connection: (schema, tables, base daily paid rows per table)
    "salesforce_prod": ("salesforce", ["account", "opportunity", "contact", "lead", "task"], 9_000),
    "netsuite": ("netsuite", ["transaction", "transaction_line", "customer", "item"], 8_000),
    "postgres_app": ("app_public", ["orders", "order_items", "users", "events"], 12_000),
    "zendesk": ("zendesk", ["ticket", "ticket_comment", "user"], 5_000),
}

DBT_MODELS = [
    # model, share of TRANSFORM_WH credits, avg seconds
    ("stg_orders", 0.04, 40), ("stg_order_items", 0.05, 55), ("stg_customers", 0.02, 20),
    ("int_order_lines", 0.10, 140), ("int_customer_ltv", 0.09, 130),
    ("fct_orders", 0.16, 260), ("fct_revenue_daily", 0.12, 190), ("dim_customers", 0.06, 80),
    ("fct_events_sessionized", 0.22, 420), ("rpt_exec_kpis", 0.05, 60),
]


def growth(t: np.ndarray, annual: float) -> np.ndarray:
    """Compound growth multiplier for day index t (0 = first day)."""
    return (1 + annual) ** (t / 365.0)


def main(db_path: str) -> None:
    rng = np.random.default_rng(SEED)
    start = END - timedelta(days=DAYS - 1)
    dates = pd.date_range(start, END, freq="D")
    t = np.arange(len(dates))
    weekday = dates.dayofweek.values
    weekday_factor = np.where(weekday >= 5, 0.55, 1.0)

    wh_rows, st_rows, sl_rows, cx_rows, ft_rows, dbt_rows = [], [], [], [], [], []

    for idx, (cid, _name, _ind, _pc, _ps, _pm, size) in enumerate(CLIENTS):
        g = growth(t, annual=[0.35, 0.22, 0.50][idx])

        # ---- warehouses (compute + cloud services)
        for wh, base in WAREHOUSES.items():
            noise = rng.normal(1.0, 0.08, len(t)).clip(0.7, 1.4)
            credits = base * size * g * weekday_factor * noise
            if cid == "c_borealis" and wh == "ADHOC_WH":
                # warehouse left running over a long weekend (auto-suspend disabled)
                incident = (dates >= "2026-08-14") & (dates <= "2026-08-17")
                credits = np.where(incident, 24 * 4, credits)  # Medium WH, 24h
            cloud = credits * rng.uniform(0.04, 0.16, len(t))
            for d, c, cs in zip(dates, credits, cloud):
                wh_rows.append((cid, d.date(), wh, round(c, 4), round(cs, 4)))

        # ---- storage (bytes, daily snapshot)
        base_tb = [42, 18, 25][idx]
        tb = base_tb * growth(t, annual=[0.45, 0.30, 0.60][idx])
        for d, v in zip(dates, tb):
            st_rows.append((cid, d.date(), int(v * 1e12), int(v * 0.04 * 1e12), int(v * 0.07 * 1e12)))

        # ---- serverless features
        for svc, base in SERVERLESS.items():
            credits = base * size * g * rng.normal(1.0, 0.15, len(t)).clip(0.5, 1.8)
            for d, c in zip(dates, credits):
                sl_rows.append((cid, d.date(), svc, round(c, 4)))

        # ---- Cortex AI: adoption S-curve from Jan 2026, different appetite per client
        adoption_mid = pd.Timestamp(["2026-03-15", "2026-06-01", "2026-02-01"][idx])
        appetite = [1.0, 0.35, 1.6][idx]
        days_from_mid = (dates - adoption_mid).days.values
        adoption = 1 / (1 + np.exp(-days_from_mid / 25.0))
        adoption = np.where(dates < pd.Timestamp("2026-01-01"), 0, adoption)
        for fn, model, cpm, base_tokens in CORTEX:
            tokens = base_tokens * appetite * adoption * weekday_factor * rng.normal(1.0, 0.2, len(t)).clip(0.3, 2.0)
            for d, tok in zip(dates, tokens):
                if tok < 1000:
                    continue
                cx_rows.append((cid, d.date(), fn, model, int(tok), round(tok / 1e6 * cpm, 6)))

        # ---- Fivetran MAR (paid incremental rows by table)
        for conn, (schema, tables, base_rows) in CONNECTORS.items():
            for tbl in tables:
                rows = base_rows * size * g * weekday_factor * rng.lognormal(0, 0.25, len(t))
                if cid == "c_aurora" and conn == "salesforce_prod":
                    # schema change -> historical re-sync of large Salesforce tables
                    spike = (dates >= "2026-05-05") & (dates <= "2026-05-09")
                    rows = np.where(spike, rows * 40, rows)
                for d, r in zip(dates, rows):
                    ft_rows.append((cid, d.date(), conn, schema, tbl, int(r), "PAID"))
                    if d.day == 1:  # Fivetran's free initial-sync style rows, not billed
                        ft_rows.append((cid, d.date(), conn, schema, tbl, int(r * 0.3), "FREE"))

        # ---- dbt runs (attribution of TRANSFORM_WH credits to models)
        transform = [r for r in wh_rows if r[0] == cid and r[2] == "TRANSFORM_WH"]
        for (_c, d, _wh, credits, _cs) in transform:
            for model, share, secs in DBT_MODELS:
                jitter = rng.normal(1.0, 0.1)
                dbt_rows.append((cid, d, model, int(secs * jitter * (1 + t[(d - start).days] / 900)),
                                 "TRANSFORM_WH", round(credits * share * jitter, 5)))

    clients = pd.DataFrame(CLIENTS, columns=[
        "client_id", "client_name", "industry", "price_per_credit",
        "storage_price_per_tb_month", "fivetran_price_per_million_mar", "size_factor"]).drop(columns="size_factor")

    frames = {
        "clients": clients,
        "warehouse_metering": pd.DataFrame(wh_rows, columns=["client_id", "usage_date", "warehouse_name", "credits_used_compute", "credits_used_cloud_services"]),
        "storage_usage": pd.DataFrame(st_rows, columns=["client_id", "usage_date", "average_database_bytes", "average_stage_bytes", "average_failsafe_bytes"]),
        "serverless_metering": pd.DataFrame(sl_rows, columns=["client_id", "usage_date", "service_type", "credits_used"]),
        "cortex_usage": pd.DataFrame(cx_rows, columns=["client_id", "usage_date", "function_name", "model_name", "tokens", "token_credits"]),
        "fivetran_mar": pd.DataFrame(ft_rows, columns=["client_id", "measured_date", "connection_name", "schema_name", "table_name", "incremental_rows", "free_type"]),
        "dbt_runs": pd.DataFrame(dbt_rows, columns=["client_id", "run_date", "model_name", "execution_seconds", "warehouse_name", "credits_attributed"]),
    }

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db_path)
    con.execute("create schema if not exists raw")
    for name, df in frames.items():
        con.register("df_tmp", df)
        con.execute(f"create or replace table raw.{name} as select * from df_tmp")
        con.unregister("df_tmp")
        print(f"raw.{name:<22} {len(df):>8,} rows")
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/spend.duckdb")
    main(parser.parse_args().db)
