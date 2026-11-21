-- Attribution of TRANSFORM warehouse cost to individual dbt models (not additive to fct_daily_spend)
select
    r.client_id,
    cast(date_trunc('month', r.usage_date) as date) as spend_month,
    r.model_name,
    count(*)                                        as runs,
    round(avg(r.execution_seconds), 1)              as avg_execution_seconds,
    round(sum(r.credits), 3)                        as credits,
    round(sum(r.credits) * max(cast(c.price_per_credit as double)), 2) as cost_usd,
    round(sum(r.credits) * max(cast(c.price_per_credit as double)) / count(*), 4) as cost_per_run_usd
from {{ ref('stg_dbt_runs') }} r
join {{ ref('stg_clients') }} c using (client_id)
group by 1, 2, 3
