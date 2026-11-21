-- Fill SPEND_COPILOT.RAW from a real account's usage views, in the same shape as
-- the synthetic data, so the dbt models, semantic layer, dashboard and MCP server
-- run unchanged with DBT_TARGET=snowflake.
--
-- Set your client id and contract prices first. For several client accounts,
-- run this once per account (or adapt it to SNOWFLAKE.ORGANIZATION_USAGE).
-- Column names follow current Snowflake/Fivetran docs; verify them on your account.

use role SPEND_COPILOT_ROLE;
use warehouse SPEND_COPILOT_WH;
use schema SPEND_COPILOT.RAW;

set CLIENT_ID = 'c_my_account';
set CLIENT_NAME = 'My Account';
set PRICE_PER_CREDIT = 3.00;
set STORAGE_PRICE_PER_TB_MONTH = 23.00;
set FIVETRAN_PRICE_PER_MILLION_MAR = 500.00;

create or replace table CLIENTS as
select $CLIENT_ID as client_id, $CLIENT_NAME as client_name, 'Unknown' as industry,
       $PRICE_PER_CREDIT as price_per_credit,
       $STORAGE_PRICE_PER_TB_MONTH as storage_price_per_tb_month,
       $FIVETRAN_PRICE_PER_MILLION_MAR as fivetran_price_per_million_mar;

create or replace table WAREHOUSE_METERING as
select $CLIENT_ID as client_id,
       to_date(start_time) as usage_date,
       warehouse_name,
       sum(credits_used_compute) as credits_used_compute,
       sum(credits_used_cloud_services) as credits_used_cloud_services
from SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
where start_time >= dateadd(month, -24, current_date())
group by 1, 2, 3;

create or replace table STORAGE_USAGE as
select $CLIENT_ID as client_id,
       d.usage_date,
       sum(d.average_database_bytes) as average_database_bytes,
       coalesce(max(s.average_stage_bytes), 0) as average_stage_bytes,
       sum(d.average_failsafe_bytes) as average_failsafe_bytes
from SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY d
left join SNOWFLAKE.ACCOUNT_USAGE.STAGE_STORAGE_USAGE_HISTORY s on s.usage_date = d.usage_date
where d.usage_date >= dateadd(month, -24, current_date())
group by 1, 2;

create or replace table SERVERLESS_METERING as
select $CLIENT_ID as client_id,
       usage_date,
       service_type,
       sum(credits_used) as credits_used
from SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
where usage_date >= dateadd(month, -24, current_date())
  and service_type not in ('WAREHOUSE_METERING', 'AI_SERVICES')  -- warehouses and Cortex are handled separately
group by 1, 2, 3;

create or replace table CORTEX_USAGE as
select $CLIENT_ID as client_id,
       to_date(start_time) as usage_date,
       function_name,
       model_name,
       sum(tokens) as tokens,
       sum(token_credits) as token_credits
from SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY
where start_time >= dateadd(month, -24, current_date())
group by 1, 2, 3, 4;

-- Fivetran writes usage to its FIVETRAN_METADATA schema (database name depends on your destination)
create or replace table FIVETRAN_MAR as
select $CLIENT_ID as client_id,
       measured_date,
       connection_name,
       schema_name,
       table_name,
       incremental_rows,
       free_type
from FIVETRAN_DB.FIVETRAN_METADATA.INCREMENTAL_MAR
where measured_date >= dateadd(month, -24, current_date());

-- dbt model cost: attribute warehouse credits to models via the dbt query tag
-- (set query_tag in profiles.yml, as this repo does). Approximation: share of
-- warehouse execution time per model per day.
create or replace table DBT_RUNS as
with q as (
    select to_date(start_time) as run_date,
           warehouse_name,
           try_parse_json(query_tag):node_id::string as node_id,
           execution_time / 1000 as execution_seconds
    from SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    where start_time >= dateadd(month, -24, current_date())
      and query_tag ilike '%node_id%'
),
model_day as (
    select run_date, warehouse_name, split_part(node_id, '.', -1) as model_name,
           sum(execution_seconds) as execution_seconds
    from q group by 1, 2, 3
),
wh_day as (
    select to_date(start_time) as run_date, warehouse_name, sum(credits_used_compute) as credits
    from SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    group by 1, 2
)
select $CLIENT_ID as client_id, m.run_date, m.model_name, m.execution_seconds::int as execution_seconds,
       m.warehouse_name,
       w.credits * m.execution_seconds / nullif(sum(m.execution_seconds) over (partition by m.run_date, m.warehouse_name), 0)
           as credits_attributed
from model_day m
join wh_day w using (run_date, warehouse_name);
