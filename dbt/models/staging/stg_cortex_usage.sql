select
    client_id,
    cast(usage_date as date)      as usage_date,
    upper(function_name)          as function_name,
    lower(model_name)             as model_name,
    cast(tokens as bigint)        as tokens,
    cast(token_credits as double) as credits
from {{ source('raw', 'cortex_usage') }}
