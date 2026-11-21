"""Data Spend Copilot - client-ready spend report + next-year forecast.

Every number comes from the dbt Semantic Layer (copilot.semantic), the same
metrics the MCP server gives to AI agents.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot import forecast as fc  # noqa: E402
from copilot import semantic, warehouse  # noqa: E402

st.set_page_config(page_title="Data Spend Copilot", page_icon="💸", layout="wide")

# Fixed category -> color mapping (reference palette slots 1-6, validated for adjacent stacks).
# Colour follows the category everywhere, whatever filter is applied.
CATEGORY_ORDER = ["compute", "ai", "ingestion", "storage", "serverless", "cloud_services"]
CATEGORY_LABEL = {"compute": "Warehouse compute", "ai": "AI / Cortex", "ingestion": "Fivetran ingestion",
                  "storage": "Storage", "serverless": "Serverless", "cloud_services": "Cloud services"}
CATEGORY_COLOR = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]


@st.cache_resource(show_spinner="First run: generating data and running dbt (about 30s)...")
def bootstrap() -> bool:
    db = ROOT / "data" / "spend.duckdb"
    if not db.exists():
        subprocess.run([sys.executable, "scripts/generate_data.py"], cwd=ROOT, check=True)
        subprocess.run(["dbt", "build", "--profiles-dir", "."], cwd=ROOT / "dbt", check=True)
    return True


@st.cache_data(show_spinner="Querying the semantic layer...")
def monthly_detail() -> pd.DataFrame:
    df = semantic.query(["total_spend"], grain="month", group_by=["client_id", "category", "sub_category"])
    df["period"] = pd.to_datetime(df["period"])
    return df


@st.cache_data(show_spinner=False)
def clients() -> pd.DataFrame:
    return warehouse.clients()


@st.cache_data(show_spinner="Forecasting...")
def run_forecast(client_id: str, compute: float, ai: float, ingestion: float) -> dict:
    return fc.forecast(client_id, fc.Scenario(compute, ai, ingestion))


def money(x: float) -> str:
    return f"${x:,.0f}"


def stacked_bar(df: pd.DataFrame, title: str) -> alt.Chart:
    df = df.assign(category_label=df["category"].map(CATEGORY_LABEL))
    return (
        alt.Chart(df, title=title)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke="#fcfcfb", strokeWidth=2)
        .encode(
            x=alt.X("yearmonth(period):O", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0)),
            y=alt.Y("sum(total_spend):Q", title="USD", axis=alt.Axis(format="$,.0f", gridOpacity=0.4)),
            color=alt.Color("category_label:N", title=None,
                            scale=alt.Scale(domain=[CATEGORY_LABEL[c] for c in CATEGORY_ORDER], range=CATEGORY_COLOR),
                            legend=alt.Legend(orient="top")),
            order=alt.Order("category_order:Q"),
            tooltip=[alt.Tooltip("yearmonth(period):T", title="Month"),
                     alt.Tooltip("category_label:N", title="Category"),
                     alt.Tooltip("sum(total_spend):Q", title="Spend", format="$,.0f")],
        )
        .transform_calculate(category_order=f"indexof({CATEGORY_ORDER}, datum.category)")
        .properties(height=340)
    )


bootstrap()
detail = monthly_detail()
client_df = clients()
names = dict(zip(client_df["client_id"], client_df["client_name"]))

st.title("💸 Data Spend Copilot")
st.caption("Snowflake + Fivetran + dbt + Cortex AI spend, in one client-ready report. "
           "Synthetic demo data; metrics served by the dbt Semantic Layer.")

f1, f2 = st.columns([2, 3])
client_id = f1.selectbox("Client", list(names), format_func=names.get)
months = sorted(detail["period"].unique())
start, end = f2.select_slider("Months", options=months, value=(months[-12], months[-1]),
                              format_func=lambda d: pd.Timestamp(d).strftime("%b %Y"))

view = detail[(detail["client_id"] == client_id) & detail["period"].between(start, end)]
prev_start = pd.Timestamp(start) - pd.DateOffset(months=len(view["period"].unique()))
prev = detail[(detail["client_id"] == client_id) & detail["period"].between(prev_start, pd.Timestamp(start) - pd.Timedelta(days=1))]

total = view["total_spend"].sum()
ai = view.loc[view["category"] == "ai", "total_spend"].sum()
ingestion = view.loc[view["category"] == "ingestion", "total_spend"].sum()
prev_total = prev["total_spend"].sum()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total spend", money(total), f"{(total / prev_total - 1) * 100:+.1f}% vs prior period" if prev_total else None,
          delta_color="inverse")
k2.metric("AI / Cortex spend", money(ai), f"{ai / total * 100:.1f}% of total" if total else None, delta_color="off")
k3.metric("Fivetran ingestion", money(ingestion), f"{ingestion / total * 100:.1f}% of total" if total else None,
          delta_color="off")
k4.metric("Avg per month", money(total / max(len(view["period"].unique()), 1)))

tab_overview, tab_ai, tab_ingest, tab_dbt, tab_anom, tab_fc = st.tabs(
    ["Overview", "AI spend", "Ingestion", "dbt models", "Anomalies", "Forecast & what-if"])

with tab_overview:
    st.altair_chart(stacked_bar(view, "Monthly spend by category"), width="stretch")
    table = (view.groupby("category", as_index=False)["total_spend"].sum()
             .assign(category=lambda d: d["category"].map(CATEGORY_LABEL),
                     share=lambda d: (d["total_spend"] / d["total_spend"].sum() * 100).round(1))
             .sort_values("total_spend", ascending=False)
             .rename(columns={"category": "Category", "total_spend": "Spend (USD)", "share": "Share %"}))
    st.dataframe(table, hide_index=True, width="stretch",
                 column_config={"Spend (USD)": st.column_config.NumberColumn(format="dollar")})

with tab_ai:
    ai_view = view[view["category"] == "ai"]
    if ai_view.empty:
        st.info("No AI usage in this period.")
    else:
        by_fn = ai_view.groupby("sub_category", as_index=False)["total_spend"].sum().sort_values("total_spend", ascending=False)
        chart = (alt.Chart(by_fn, title="AI spend by function / model")
                 .mark_bar(cornerRadiusEnd=4, color="#eb6834")
                 .encode(y=alt.Y("sub_category:N", sort="-x", title=None),
                         x=alt.X("total_spend:Q", title="USD", axis=alt.Axis(format="$,.0f", gridOpacity=0.4)),
                         tooltip=[alt.Tooltip("sub_category:N", title="Function / model"),
                                  alt.Tooltip("total_spend:Q", title="Spend", format="$,.0f")])
                 .properties(height=260))
        st.altair_chart(chart, width="stretch")
        st.caption("AI spend is a new budget line most teams don't forecast yet. The Forecast tab lets you test adoption scenarios.")

with tab_ingest:
    ing = view[view["category"] == "ingestion"]
    by_conn = ing.groupby(["period", "sub_category"], as_index=False)["total_spend"].sum()
    chart = (alt.Chart(by_conn, title="Fivetran spend by connector")
             .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
             .encode(x=alt.X("yearmonth(period):T", title=None),
                     y=alt.Y("total_spend:Q", title="USD", axis=alt.Axis(format="$,.0f", gridOpacity=0.4)),
                     color=alt.Color("sub_category:N", title=None, legend=alt.Legend(orient="top"),
                                     scale=alt.Scale(range=CATEGORY_COLOR[:4])),
                     tooltip=[alt.Tooltip("yearmonth(period):T", title="Month"),
                              alt.Tooltip("sub_category:N", title="Connector"),
                              alt.Tooltip("total_spend:Q", title="Spend", format="$,.0f")])
             .properties(height=320))
    st.altair_chart(chart, width="stretch")

with tab_dbt:
    since = pd.Timestamp(start).date().isoformat()
    models = warehouse.top_dbt_models(client_id, since, 10)
    st.write("Most expensive dbt models (cost attributed from the transform warehouse; not added to totals).")
    st.dataframe(models, hide_index=True, width="stretch",
                 column_config={"cost_usd": st.column_config.NumberColumn("Cost (USD)", format="dollar")})

with tab_anom:
    anomalies = warehouse.anomalies(pd.Timestamp(start).date().isoformat(), client_id)
    if anomalies.empty:
        st.success("No spend anomalies in this period.")
    else:
        st.warning(f"{len(anomalies)} anomalous day(s): spend far above the 28-day baseline.")
        st.dataframe(anomalies, hide_index=True, width="stretch")

with tab_fc:
    st.write("Next 12 months, from the median monthly growth of each cost line. Move the levers to test scenarios.")
    c1, c2, c3 = st.columns(3)
    compute_adj = c1.slider("Extra compute growth (%)", -30, 100, 0, 5)
    ai_mult = c2.slider("AI usage multiplier", 0.5, 4.0, 1.0, 0.25)
    ingest_adj = c3.slider("New connectors: extra rows (%)", -30, 200, 0, 10)
    result = run_forecast(client_id, compute_adj, ai_mult, ingest_adj)

    m1, m2, m3 = st.columns(3)
    m1.metric("Last 12 months", money(result["last_12m_total_usd"]))
    m2.metric("Next 12 months (forecast)", money(result["next_12m_total_usd"]),
              f"{(result['next_12m_total_usd'] / result['last_12m_total_usd'] - 1) * 100:+.1f}%", delta_color="inverse")
    m3.metric("Likely range", f"{money(result['next_12m_low_usd'])} - {money(result['next_12m_high_usd'])}")

    hist = result["history"].melt(id_vars="period", var_name="series", value_name="usd").assign(kind="Actual")
    fut = result["forecast_by_month"].melt(id_vars="period", var_name="series", value_name="usd").assign(kind="Forecast")
    both = pd.concat([hist, fut]).groupby(["period", "kind"], as_index=False)["usd"].sum()
    both["period"] = pd.to_datetime(both["period"])
    chart = (alt.Chart(both, title="Total monthly spend: actual vs forecast")
             .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
             .encode(x=alt.X("yearmonth(period):T", title=None),
                     y=alt.Y("usd:Q", title="USD", axis=alt.Axis(format="$,.0f", gridOpacity=0.4)),
                     color=alt.Color("kind:N", title=None, scale=alt.Scale(range=["#2a78d6", "#eb6834"]),
                                     legend=alt.Legend(orient="top")),
                     strokeDash=alt.StrokeDash("kind:N", legend=None, scale=alt.Scale(range=[[1, 0], [6, 4]])),
                     tooltip=[alt.Tooltip("yearmonth(period):T", title="Month"), alt.Tooltip("kind:N"),
                              alt.Tooltip("usd:Q", title="Spend", format="$,.0f")])
             .properties(height=320))
    st.altair_chart(chart, width="stretch")
    growth = pd.DataFrame([{"Cost line": k.replace("_", " "), "Monthly growth used (%)": v}
                           for k, v in result["monthly_growth_pct_by_series"].items()])
    st.dataframe(growth, hide_index=True, width="stretch")
