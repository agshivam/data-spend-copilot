"""Query governed metrics through the dbt Semantic Layer (MetricFlow).

Every number the dashboard or the AI agent shows comes through here, so metric
logic lives in exactly one place: dbt/models/semantic/spend_semantic.yml.
Inputs are validated against allow-lists, so an agent cannot inject SQL.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt"
SEMANTIC_FILE = DBT_DIR / "models" / "semantic" / "spend_semantic.yml"

GRAINS = {"day", "week", "month", "quarter", "year"}
GROUP_BYS = {
    "client": "client__client_name",
    "client_id": "client",
    "industry": "client__industry",
    "platform": "spend_item__platform",
    "category": "spend_item__category",
    "sub_category": "spend_item__sub_category",
}
_CLIENT_ID = re.compile(r"^[a-z0-9_]{1,40}$")


class QueryError(ValueError):
    """Raised for invalid metric queries (bad metric, dimension, date or scope)."""


def list_metrics() -> list[dict]:
    spec = yaml.safe_load(SEMANTIC_FILE.read_text())
    return [
        {"name": m["name"], "label": m.get("label", m["name"]), "description": m.get("description", "")}
        for m in spec["metrics"]
    ]


def _metric_names() -> set[str]:
    return {m["name"] for m in list_metrics()}


def query(
    metrics: list[str],
    grain: str | None = "month",
    group_by: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    client_id: str | None = None,
) -> pd.DataFrame:
    """Run a semantic-layer query and return a tidy DataFrame.

    metrics:    names from spend_semantic.yml (e.g. ["ai_spend", "total_spend"])
    grain:      day/week/month/quarter/year, or None for a single total
    group_by:   friendly names from GROUP_BYS (e.g. ["client", "category"])
    client_id:  restrict to one client (row-level scope)
    """
    known = _metric_names()
    bad = [m for m in metrics if m not in known]
    if not metrics or bad:
        raise QueryError(f"Unknown metric(s): {bad or metrics}. Available: {sorted(known)}")

    dims: list[str] = []
    if grain:
        if grain not in GRAINS:
            raise QueryError(f"grain must be one of {sorted(GRAINS)}")
        dims.append(f"metric_time__{grain}")
    for g in group_by or []:
        if g not in GROUP_BYS:
            raise QueryError(f"Unknown group_by '{g}'. Available: {sorted(GROUP_BYS)}")
        dims.append(GROUP_BYS[g])

    cmd = ["mf", "query", "--metrics", ",".join(metrics)]
    if dims:
        cmd += ["--group-by", ",".join(dims)]
    for flag, value in (("--start-time", start_date), ("--end-time", end_date)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise QueryError(f"Dates must be YYYY-MM-DD, got {value!r}") from exc
            cmd += [flag, value]
    if client_id:
        if not _CLIENT_ID.match(client_id):
            raise QueryError("Invalid client_id")
        cmd += ["--where", f"{{{{ Entity('client') }}}} = '{client_id}'"]
    if grain:
        cmd += ["--order", f"metric_time__{grain}"]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.csv"
        env = {**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)}
        env.setdefault("SPEND_DB", str(ROOT / "data" / "spend.duckdb"))
        proc = subprocess.run(cmd + ["--csv", str(out)], cwd=DBT_DIR, env=env,
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not out.exists():
            raise QueryError(f"MetricFlow query failed: {(proc.stderr or proc.stdout)[-800:]}")
        df = pd.read_csv(out)

    rename = {f"metric_time__{grain}": "period"} if grain else {}
    rename |= {v: k for k, v in GROUP_BYS.items()}
    df = df.rename(columns=rename)
    if "period" in df:
        df["period"] = pd.to_datetime(df["period"]).dt.date
    return df
