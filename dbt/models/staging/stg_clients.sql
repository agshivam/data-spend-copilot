select
    client_id,
    client_name,
    industry,
    cast(price_per_credit as decimal(10, 4))               as price_per_credit,
    cast(storage_price_per_tb_month as decimal(10, 4))     as storage_price_per_tb_month,
    cast(fivetran_price_per_million_mar as decimal(10, 4)) as fivetran_price_per_million_mar
from {{ source('raw', 'clients') }}
