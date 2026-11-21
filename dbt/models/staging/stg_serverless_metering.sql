select
    client_id,
    cast(usage_date as date)     as usage_date,
    upper(service_type)          as service_type,
    cast(credits_used as double) as credits
from {{ source('raw', 'serverless_metering') }}
