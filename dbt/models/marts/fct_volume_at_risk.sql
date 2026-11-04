-- Volume and value at risk per component (AC), product (PF) and forecast quarter (TODO item 2).
-- Grain: snapshot_quarter x ac_code x pf_code x forecast_quarter.
--
-- Question: "If I don't invest and don't use CMs, how many products can't I make, and what
-- is that worth?" So capacity = BASELINE capacity only (today's lines, no CMs), against
--   baseline: the baseline (reference) forecast
--   stretch:  the stretch (high) forecast, still without CMs
--
-- Rules (decisions in TODO.md):
--   shortfall (pieces)  = max(component demand - baseline capacity, 0), per AC and quarter
--   D1 allocation       every product using the AC loses the same share of its forecast:
--                       units_at_risk = PF forecast x shortfall / AC demand
--                       (= the shortfall split by each PF's share of the AC demand, in PF units)
--   D2 price            int_pf_price (net sales / units, latest 4 history quarters)
--   D3 cost             int_pf_packaging_cost: packaging only, so
--                       contribution = units x (price - packaging cost), BEFORE all other costs
--   Launches (NPD) have no price: units are counted, euros stay null (never guessed).
--
-- One PF short on two components does NOT lose both amounts: summing this table over
-- components double counts. Per-product totals are in fct_product_volume_at_risk.
-- Only components with capacity data (those in fct_saturation) can be assessed.

with saturation as (

    select * from {{ ref('fct_saturation') }}

),

forecast as (

    select * from {{ ref('stg_finance_forecast') }}

),

bom as (

    select * from {{ ref('int_bom') }}

),

-- shortfall per component and quarter, without CMs
shortfall as (

    select
        snapshot_quarter,
        ac_code,
        forecast_quarter,
        qty_baseline                                       as ac_qty_baseline,
        qty_stretch                                        as ac_qty_stretch,
        baseline_capacity,
        greatest(qty_baseline - baseline_capacity, 0)      as shortfall_baseline,
        greatest(qty_stretch  - baseline_capacity, 0)      as shortfall_stretch
    from saturation

),

-- each product using the component, with its own forecast
product_demand as (

    select
        b.snapshot_quarter,
        b.ac_code,
        b.pf_code,
        f.forecast_quarter,
        b.qty_per_pf,
        f.qty_baseline as pf_qty_baseline,
        f.qty_stretch  as pf_qty_stretch,
        f.is_stretch_imputed
    from bom b
    join forecast f
        on  f.snapshot_quarter = b.snapshot_quarter
        and f.pf_code = b.pf_code

),

allocated as (

    select
        s.snapshot_quarter,
        s.ac_code,
        d.pf_code,
        s.forecast_quarter,
        d.qty_per_pf,
        d.pf_qty_baseline,
        d.pf_qty_stretch,
        d.is_stretch_imputed,
        s.ac_qty_baseline,
        s.ac_qty_stretch,
        s.baseline_capacity,
        s.shortfall_baseline,
        s.shortfall_stretch,
        d.pf_qty_baseline * s.shortfall_baseline / nullif(s.ac_qty_baseline, 0) as units_at_risk_baseline,
        d.pf_qty_stretch  * s.shortfall_stretch  / nullif(s.ac_qty_stretch, 0)  as units_at_risk_stretch
    from shortfall s
    join product_demand d
        on  d.snapshot_quarter = s.snapshot_quarter
        and d.ac_code = s.ac_code
        and d.forecast_quarter = s.forecast_quarter

)

select
    a.snapshot_quarter || '|' || a.ac_code || '|' || a.pf_code || '|' || a.forecast_quarter
                                                         as volume_at_risk_key,
    a.snapshot_quarter,
    a.ac_code,
    a.pf_code,
    a.forecast_quarter,
    left(a.forecast_quarter, 4)::int                     as forecast_year,
    a.qty_per_pf,
    a.pf_qty_baseline,
    a.pf_qty_stretch,
    a.is_stretch_imputed,                                -- the PF's stretch forecast was blank (staging)
    a.ac_qty_baseline,
    a.ac_qty_stretch,
    a.baseline_capacity,
    a.shortfall_baseline,
    a.shortfall_stretch,
    round(coalesce(a.units_at_risk_baseline, 0), 4)      as units_at_risk_baseline,
    round(coalesce(a.units_at_risk_stretch, 0), 4)       as units_at_risk_stretch,
    p.price_eur_per_unit,
    c.packaging_cost_eur_per_unit,
    p.price_eur_per_unit is not null                     as has_price,
    round(coalesce(a.units_at_risk_baseline, 0) * p.price_eur_per_unit, 2) as revenue_at_risk_baseline,
    round(coalesce(a.units_at_risk_stretch, 0)  * p.price_eur_per_unit, 2) as revenue_at_risk_stretch,
    round(coalesce(a.units_at_risk_baseline, 0)
          * (p.price_eur_per_unit - c.packaging_cost_eur_per_unit), 2)    as contribution_at_risk_baseline,
    round(coalesce(a.units_at_risk_stretch, 0)
          * (p.price_eur_per_unit - c.packaging_cost_eur_per_unit), 2)    as contribution_at_risk_stretch
from allocated a
left join {{ ref('int_pf_price') }} p
    on  p.snapshot_quarter = a.snapshot_quarter
    and p.pf_code = a.pf_code
left join {{ ref('int_pf_packaging_cost') }} c
    on  c.snapshot_quarter = a.snapshot_quarter
    and c.pf_code = a.pf_code
