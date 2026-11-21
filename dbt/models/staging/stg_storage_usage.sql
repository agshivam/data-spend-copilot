select
    client_id,
    cast(usage_date as date) as usage_date,
    (average_database_bytes + average_stage_bytes + average_failsafe_bytes) / 1e12 as storage_tb,
    average_failsafe_bytes / 1e12 as failsafe_tb
from {{ source('raw', 'storage_usage') }}
