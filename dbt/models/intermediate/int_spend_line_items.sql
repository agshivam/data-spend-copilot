-- One row per client / day / billable item, all priced in USD.
-- dbt model costs are NOT here on purpose: they are an attribution of warehouse
-- compute (see fct_dbt_model_cost), and adding them would double count.

with clients as (
    select * from {{ ref('stg_clients') }}
),

warehouse as (
    select * from {{ ref('stg_warehouse_metering') }}
),

compute_cost as (
    select
        w.client_id,
        w.usage_date                         as spend_date,
        'snowflake'                          as platform,
        'compute'                            as category,
        w.warehouse_name                     as sub_category,
        w.compute_credits                    as usage_quantity,
        'credits'                            as usage_unit,
        w.compute_credits * cast(c.price_per_credit as double) as cost_usd
    from warehouse w
    join clients c using (client_id)
),

-- Cloud services are only billed above 10% of the day's compute credits (per account)
cloud_services_daily as (
    select
        client_id,
        usage_date,
        sum(compute_credits)        as compute_credits,
        sum(cloud_services_credits) as cloud_services_credits
    from warehouse
    group by 1, 2
),

cloud_services_cost as (
    select
        d.client_id,
        d.usage_date                         as spend_date,
        'snowflake'                          as platform,
        'cloud_services'                     as category,
        'CLOUD_SERVICES_BILLABLE'            as sub_category,
        greatest(0, d.cloud_services_credits - {{ var('cloud_services_free_ratio') }} * d.compute_credits) as usage_quantity,
        'credits'                            as usage_unit,
        greatest(0, d.cloud_services_credits - {{ var('cloud_services_free_ratio') }} * d.compute_credits)
            * cast(c.price_per_credit as double) as cost_usd
    from cloud_services_daily d
    join clients c using (client_id)
),

storage_cost as (
    select
        s.client_id,
        s.usage_date                         as spend_date,
        'snowflake'                          as platform,
        'storage'                            as category,
        'STORAGE_TB'                         as sub_category,
        s.storage_tb                         as usage_quantity,
        'tb'                                 as usage_unit,
        -- price is per TB-month; spread evenly across the days of the month
        s.storage_tb * cast(c.storage_price_per_tb_month as double)
            / extract(day from last_day(s.usage_date)) as cost_usd
    from {{ ref('stg_storage_usage') }} s
    join clients c using (client_id)
),

serverless_cost as (
    select
        s.client_id,
        s.usage_date                         as spend_date,
        'snowflake'                          as platform,
        'serverless'                         as category,
        s.service_type                       as sub_category,
        s.credits                            as usage_quantity,
        'credits'                            as usage_unit,
        s.credits * cast(c.price_per_credit as double) as cost_usd
    from {{ ref('stg_serverless_metering') }} s
    join clients c using (client_id)
),

ai_cost as (
    select
        a.client_id,
        a.usage_date                         as spend_date,
        'snowflake'                          as platform,
        'ai'                                 as category,
        a.function_name || ' / ' || a.model_name as sub_category,
        cast(a.tokens as double)             as usage_quantity,
        'tokens'                             as usage_unit,
        a.credits * cast(c.price_per_credit as double) as cost_usd
    from {{ ref('stg_cortex_usage') }} a
    join clients c using (client_id)
),

ingestion_cost as (
    select
        f.client_id,
        f.usage_date                         as spend_date,
        'fivetran'                           as platform,
        'ingestion'                          as category,
        f.connection_name                    as sub_category,
        cast(sum(f.incremental_rows) as double) as usage_quantity,
        'paid_rows'                          as usage_unit,
        -- simplified flat rate; real Fivetran pricing is tiered (see README)
        sum(f.incremental_rows) / 1e6 * max(cast(c.fivetran_price_per_million_mar as double)) as cost_usd
    from {{ ref('stg_fivetran_mar') }} f
    join clients c using (client_id)
    where f.is_paid
    group by 1, 2, 3, 4, 5
)

select * from compute_cost
union all select * from cloud_services_cost
union all select * from storage_cost
union all select * from serverless_cost
union all select * from ai_cost
union all select * from ingestion_cost
