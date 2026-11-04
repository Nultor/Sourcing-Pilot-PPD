-- Volume and value at risk per product (PF) and forecast quarter, without CMs or investment.
-- Grain: snapshot_quarter x pf_code x forecast_quarter. Safe to sum (over products, quarters).
--
-- A product needs ALL its components: if two are short, it loses the LARGER of the two
-- shares, not the sum. So units at risk = max over the product's components in
-- fct_volume_at_risk, and binding_ac_code is the component that causes it.
-- Euros as in fct_volume_at_risk: price from sales history, contribution = price minus
-- packaging cost only; null for launches (no price).

with per_component as (

    select * from {{ ref('fct_volume_at_risk') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by snapshot_quarter, pf_code, forecast_quarter
            order by units_at_risk_baseline desc, units_at_risk_stretch desc, ac_code
        ) as baseline_rank,
        row_number() over (
            partition by snapshot_quarter, pf_code, forecast_quarter
            order by units_at_risk_stretch desc, units_at_risk_baseline desc, ac_code
        ) as stretch_rank
    from per_component

),

per_product as (

    select
        snapshot_quarter,
        pf_code,
        forecast_quarter,
        max(forecast_year)                                  as forecast_year,
        max(pf_qty_baseline)                                as pf_qty_baseline,
        max(pf_qty_stretch)                                 as pf_qty_stretch,
        max(units_at_risk_baseline)                         as units_at_risk_baseline,
        max(units_at_risk_stretch)                          as units_at_risk_stretch,
        max(ac_code) filter (where baseline_rank = 1 and units_at_risk_baseline > 0) as binding_ac_code_baseline,
        max(ac_code) filter (where stretch_rank = 1 and units_at_risk_stretch > 0)   as binding_ac_code_stretch,
        count(*) filter (where units_at_risk_baseline > 0)  as n_components_short_baseline,
        count(*) filter (where units_at_risk_stretch > 0)   as n_components_short_stretch,
        max(price_eur_per_unit)                             as price_eur_per_unit,
        max(packaging_cost_eur_per_unit)                    as packaging_cost_eur_per_unit,
        bool_and(has_price)                                 as has_price
    from ranked
    group by 1, 2, 3

)

select
    snapshot_quarter || '|' || pf_code || '|' || forecast_quarter as product_volume_at_risk_key,
    snapshot_quarter,
    pf_code,
    forecast_quarter,
    forecast_year,
    pf_qty_baseline,
    pf_qty_stretch,
    units_at_risk_baseline,
    units_at_risk_stretch,
    binding_ac_code_baseline,
    binding_ac_code_stretch,
    n_components_short_baseline,
    n_components_short_stretch,
    price_eur_per_unit,
    packaging_cost_eur_per_unit,
    has_price,
    round(units_at_risk_baseline * price_eur_per_unit, 2)                               as revenue_at_risk_baseline,
    round(units_at_risk_stretch  * price_eur_per_unit, 2)                               as revenue_at_risk_stretch,
    round(units_at_risk_baseline * (price_eur_per_unit - packaging_cost_eur_per_unit), 2) as contribution_at_risk_baseline,
    round(units_at_risk_stretch  * (price_eur_per_unit - packaging_cost_eur_per_unit), 2) as contribution_at_risk_stretch
from per_product
