-- Only PAID rows are billed; FREE rows (e.g. initial syncs) are kept for visibility
select
    client_id,
    cast(measured_date as date)       as usage_date,
    lower(connection_name)            as connection_name,
    lower(schema_name)                as schema_name,
    lower(table_name)                 as table_name,
    cast(incremental_rows as bigint)  as incremental_rows,
    upper(free_type) = 'PAID'         as is_paid
from {{ source('raw', 'fivetran_mar') }}
