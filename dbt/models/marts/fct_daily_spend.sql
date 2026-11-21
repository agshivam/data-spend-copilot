select
    md5(client_id || '|' || cast(spend_date as varchar) || '|' || category || '|' || sub_category) as spend_id,
    client_id,
    spend_date,
    cast(date_trunc('month', spend_date) as date) as spend_month,
    platform,
    category,
    sub_category,
    usage_quantity,
    usage_unit,
    round(cost_usd, 4) as cost_usd
from {{ ref('int_spend_line_items') }}
