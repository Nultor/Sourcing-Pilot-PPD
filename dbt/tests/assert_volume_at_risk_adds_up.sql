-- The allocation of fct_volume_at_risk must add up and stay physical. Returns bad rows:
--   1. per component and quarter, the units at risk x pieces per product of all its products
--      must give back the component shortfall (nothing lost or invented by the split)
--   2. no product loses more units than its forecast, and never a negative amount

with per_component as (

    select
        snapshot_quarter,
        ac_code,
        forecast_quarter,
        max(shortfall_baseline)                      as shortfall_baseline,
        sum(units_at_risk_baseline * qty_per_pf)     as allocated_baseline,
        max(shortfall_stretch)                       as shortfall_stretch,
        sum(units_at_risk_stretch * qty_per_pf)      as allocated_stretch
    from {{ ref('fct_volume_at_risk') }}
    group by 1, 2, 3

)

select snapshot_quarter, ac_code, forecast_quarter, null as pf_code, 'allocation does not add up' as problem
from per_component
where abs(allocated_baseline - shortfall_baseline) > 0.01
   or abs(allocated_stretch - shortfall_stretch) > 0.01

union all

select snapshot_quarter, ac_code, forecast_quarter, pf_code, 'units at risk outside 0..forecast'
from {{ ref('fct_volume_at_risk') }}
where units_at_risk_baseline < 0
   or units_at_risk_stretch < 0
   or units_at_risk_baseline > pf_qty_baseline + 0.01
   or units_at_risk_stretch > pf_qty_stretch + 0.01
