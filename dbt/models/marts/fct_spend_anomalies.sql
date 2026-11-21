-- Flags days where a client's spend in a category jumps far above its trailing 28-day baseline
with daily as (
    select client_id, spend_date, category, sum(cost_usd) as cost_usd
    from {{ ref('fct_daily_spend') }}
    group by 1, 2, 3
),

scored as (
    select
        *,
        avg(cost_usd) over w         as baseline_usd,
        stddev_samp(cost_usd) over w as baseline_stddev
    from daily
    window w as (partition by client_id, category order by spend_date
                 rows between 28 preceding and 1 preceding)
)

select
    client_id,
    spend_date,
    category,
    round(cost_usd, 2)     as cost_usd,
    round(baseline_usd, 2) as baseline_usd,
    round((cost_usd - baseline_usd) / nullif(baseline_stddev, 0), 2) as z_score,
    round(cost_usd - baseline_usd, 2) as excess_usd
from scored
where baseline_stddev > 0
  and (cost_usd - baseline_usd) / baseline_stddev >= {{ var('anomaly_z_threshold') }}
  and cost_usd - baseline_usd >= 50  -- ignore tiny absolute changes
