-- Selling price per finished product (PF), from the finance sales history (TODO decision D2).
-- Grain: snapshot_quarter x pf_code.
--
--   price = sum(net sales EUR) / sum(units sold) over the latest N history quarters
--           (N = var price_history_quarters, default 4)
--
-- A total over several quarters, not an average of quarterly prices, so a big quarter
-- weighs more. Launches (NPD) have no sales history and so no row here: their price is
-- unknown and must stay unknown, never guessed.

with sales_ranked as (

    select
        snapshot_quarter,
        pf_code,
        quarter,
        qty_sold,
        net_sales_eur,
        row_number() over (
            partition by snapshot_quarter, pf_code
            order by quarter desc
        ) as row_num
    from {{ ref('stg_finance_sales_history') }}

)

select
    snapshot_quarter,
    pf_code,
    round(sum(net_sales_eur) / nullif(sum(qty_sold), 0), 4) as price_eur_per_unit,
    count(*)                                                as n_price_quarters,
    min(quarter)                                            as price_from_quarter,
    max(quarter)                                            as price_to_quarter
from sales_ranked
where row_num <= {{ var('price_history_quarters') }}
group by 1, 2
