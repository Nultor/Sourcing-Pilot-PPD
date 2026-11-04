-- Product (PF) dimension: what each finished product is.
-- Grain: snapshot_quarter x pf_code.
--
-- Products on sale come from the finance sales history (one row per quarter there, so the
-- latest quarter's attributes are kept). Products in the launch pipeline (NPD) come from
-- npd_projects until they appear in the sales history. NPD rows have no brand or format
-- column: both are read from the description ('Vireo Hair Pure Detox cream 75ml').
-- Hero = the finance "business driver" flag; NPD products aren't on sale, so never hero.

with sales_ranked as (

    select
        snapshot_quarter,
        pf_code,
        pf_description,
        brand,
        format_ml,
        is_business_driver,
        row_number() over (
            partition by snapshot_quarter, pf_code
            order by quarter desc
        ) as row_num
    from {{ ref('stg_finance_sales_history') }}

),

on_sale as (

    select
        snapshot_quarter,
        pf_code,
        pf_description,
        brand,
        format_ml,
        is_business_driver as is_hero
    from sales_ranked
    where row_num = 1

),

brands as (

    select distinct snapshot_quarter, brand
    from on_sale

),

-- npd_projects is a BOM (one row per PF x component): one row per PF
npd as (

    select distinct snapshot_quarter, pf_code, pf_description, launch_quarter
    from {{ ref('stg_npd_projects') }}

),

npd_described as (

    select
        n.snapshot_quarter,
        n.pf_code,
        n.pf_description,
        b.brand,                                   -- the description starts with the brand
        -- the description ends with the size: '75ml', '0,5 L' -> number + unit
        regexp_match(lower(replace(n.pf_description, ',', '.')), '([0-9.]+)\s*(ml|l)$') as format_parts,
        n.launch_quarter
    from npd n
    left join brands b
        on  b.snapshot_quarter = n.snapshot_quarter
        and n.pf_description ilike b.brand || ' %'

)

select
    snapshot_quarter || '|' || pf_code as product_key,
    snapshot_quarter,
    pf_code,
    pf_description,
    brand,
    format_ml,
    is_hero,
    false          as is_npd,
    null::text     as launch_quarter
from on_sale

union all

-- an NPD product that is already in the sales history is taken from there only
select
    n.snapshot_quarter || '|' || n.pf_code as product_key,
    n.snapshot_quarter,
    n.pf_code,
    n.pf_description,
    n.brand,
    n.format_parts[1]::numeric
        * case n.format_parts[2] when 'l' then 1000 when 'ml' then 1 end as format_ml,
    false          as is_hero,
    true           as is_npd,
    n.launch_quarter
from npd_described n
where not exists (
    select 1
    from on_sale s
    where s.snapshot_quarter = n.snapshot_quarter
      and s.pf_code = n.pf_code
)
