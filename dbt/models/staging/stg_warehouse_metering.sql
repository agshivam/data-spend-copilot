select
    client_id,
    cast(usage_date as date)                          as usage_date,
    upper(warehouse_name)                             as warehouse_name,
    cast(credits_used_compute as double)              as compute_credits,
    cast(credits_used_cloud_services as double)       as cloud_services_credits
from {{ source('raw', 'warehouse_metering') }}
