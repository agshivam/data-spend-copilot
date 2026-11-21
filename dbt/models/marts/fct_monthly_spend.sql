with monthly as (
    select
        client_id,
        spend_month,
        platform,
        category,
        sum(cost_usd) as cost_usd
    from {{ ref('fct_daily_spend') }}
    group by 1, 2, 3, 4
)

select
    client_id,
    spend_month,
    platform,
    category,
    round(cost_usd, 2) as cost_usd,
    round(cost_usd - lag(cost_usd) over (
        partition by client_id, platform, category order by spend_month), 2) as mom_change_usd,
    round(100.0 * (cost_usd / nullif(lag(cost_usd) over (
        partition by client_id, platform, category order by spend_month), 0) - 1), 1) as mom_change_pct
from monthly
