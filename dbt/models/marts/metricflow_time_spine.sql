-- Daily calendar required by the dbt Semantic Layer (MetricFlow)
{% if target.type == 'snowflake' %}
select dateadd(day, seq4(), '2024-01-01'::date) as date_day
from table(generator(rowcount => 1827))
{% else %}
select cast(range as date) as date_day
from range(date '2024-01-01', date '2029-01-01', interval 1 day)
{% endif %}
