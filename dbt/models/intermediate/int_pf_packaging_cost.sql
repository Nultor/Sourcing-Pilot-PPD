-- Packaging cost per finished product (PF): what the components of one unit cost
-- (TODO decision D3). Grain: snapshot_quarter x pf_code.
--
--   packaging cost = sum over the PF's BOM of (standard price per piece x pieces per PF)
--
-- Standard price = finance std cost of the latest fiscal year in the snapshot. This is
-- ONLY packaging: no liquid, labour, logistics or overheads (they aren't in the data).
-- New components for launches have no standard price yet: then the cost is incomplete
-- (has_full_packaging_cost = false) and left null rather than understated.

with std_cost as (

    select
        snapshot_quarter,
        ac_code,
        std_price_eur_per_piece,
        is_std_price_imputed,
        row_number() over (
            partition by snapshot_quarter, ac_code
            order by fiscal_year desc
        ) as row_num
    from {{ ref('stg_finance_std_cost') }}

),

latest_std_cost as (

    select * from std_cost where row_num = 1

)

select
    b.snapshot_quarter,
    b.pf_code,
    case when count(c.ac_code) = count(*)
         then round(sum(c.std_price_eur_per_piece * b.qty_per_pf), 4) end  as packaging_cost_eur_per_unit,
    count(*)                                         as n_components,
    count(c.ac_code)                                 as n_components_costed,
    count(c.ac_code) = count(*)                      as has_full_packaging_cost,
    coalesce(bool_or(c.is_std_price_imputed), false) as uses_imputed_std_price
from {{ ref('int_bom') }} b
left join latest_std_cost c
    on  c.snapshot_quarter = b.snapshot_quarter
    and c.ac_code = b.ac_code
group by 1, 2
