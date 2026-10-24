-- Quarterly sales per finished product (PF).
-- Grain: snapshot_quarter x pf_code x quarter.

with typed as (

    select
        snapshot_quarter,
        {{ clean_code('pf_code') }}          as pf_code,
        nullif(trim(pf_description), '')     as pf_description,
        nullif(trim(brand), '')              as brand,
        nullif(trim(format), '')             as format_raw,
        -- '0,5 L', '500ML', '50 ml' -> number + unit
        regexp_match(lower(replace(trim(format), ',', '.')), '^([0-9.]+)\s*(ml|l)$') as format_parts,
        {{ to_bool('business_driver') }}     as is_business_driver,
        trim(quarter)                        as quarter,
        {{ to_numeric('qty_sold') }}         as qty_sold,
        {{ to_numeric('net_sales_eur') }}    as net_sales_eur
    from {{ source('raw', 'finance_sales_history') }}

),

-- the finance extract repeats some rows: keep one per PF and quarter
deduplicated as (

    select
        *,
        row_number() over (
            partition by snapshot_quarter, pf_code, quarter
            order by qty_sold desc
        ) as row_num
    from typed

)

select
    snapshot_quarter,
    pf_code,
    pf_description,
    brand,
    format_raw,
    format_parts[1]::numeric
        * case format_parts[2] when 'l' then 1000 when 'ml' then 1 end as format_ml,
    is_business_driver,
    quarter,
    qty_sold,
    net_sales_eur
from deduplicated
where row_num = 1
