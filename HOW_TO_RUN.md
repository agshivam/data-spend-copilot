# How to run

Everything works from a browser (iPad included). Pick one option.

## Option 1: GitHub Actions (zero setup)

Push to `main` (or Actions → CI → *Run workflow*). The workflow generates the data, runs `dbt build` with all data tests, validates the semantic layer, runs a sample metric query and runs the MCP end-to-end tests. Open the run log to see the results.

## Option 2: Live dashboard on Streamlit Community Cloud (free)

1. Go to https://share.streamlit.io → **Create app** → pick this repo.
2. Branch `main`, main file `app/streamlit_app.py` → **Deploy**.
3. The first load takes about 30–60s: the app generates the data and runs dbt itself.

## Option 3: GitHub Codespaces (full terminal in the browser)

```bash
pip install -r requirements.txt
python scripts/generate_data.py              # synthetic raw data -> data/spend.duckdb
cd dbt && dbt build --profiles-dir . && cd ..   # models + tests
cd dbt && DBT_PROFILES_DIR=. mf query --metrics total_spend,ai_spend --group-by metric_time__month,client__client_name && cd ..
pytest -q tests                               # MCP server end-to-end tests
streamlit run app/streamlit_app.py            # dashboard (Codespaces forwards the port)
python -m mcp_server.server                   # MCP server over stdio
```

## Connect the MCP server to Claude Desktop (on a computer)

Copy `mcp_server/claude_desktop_config.example.json` into Claude Desktop's config, set the paths, restart Claude, then ask: *"Why did Aurora's spend jump in May 2026?"*

Set `COPILOT_CLIENT_SCOPE=c_cascade` to lock the server to one client.

## Run on a real Snowflake account

1. Run `sql/snowflake/00_setup.sql` as ACCOUNTADMIN (creates an XS auto-suspend warehouse and a least-privilege role).
2. Edit prices and the client id at the top of `sql/snowflake/01_extract_raw.sql`, then run it.
3. `pip install dbt-snowflake "snowflake-connector-python[pandas]"`, set `DBT_TARGET=snowflake` and the `SNOWFLAKE_*` variables listed in `dbt/profiles.yml`, then run `dbt build` and the app as above.
