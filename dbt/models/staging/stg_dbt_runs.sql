select
    client_id,
    cast(run_date as date)             as usage_date,
    lower(model_name)                  as model_name,
    cast(execution_seconds as integer) as execution_seconds,
    upper(warehouse_name)              as warehouse_name,
    cast(credits_attributed as double) as credits
from {{ source('raw', 'dbt_runs') }}
