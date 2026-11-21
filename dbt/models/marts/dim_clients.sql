select
    client_id,
    client_name,
    industry,
    price_per_credit,
    storage_price_per_tb_month,
    fivetran_price_per_million_mar
from {{ ref('stg_clients') }}
