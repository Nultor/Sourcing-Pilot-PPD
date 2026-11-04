-- A product short on several components loses the LARGEST share, not the sum.
-- Returns product x quarter rows where fct_product_volume_at_risk isn't the max over
-- its components in fct_volume_at_risk, or where the euros don't follow from the units.

with expected as (

    select
        snapshot_quarter, pf_code, forecast_quarter,
        max(units_at_risk_baseline) as units_at_risk_baseline,
        max(units_at_risk_stretch)  as units_at_risk_stretch
    from {{ ref('fct_volume_at_risk') }}
    group by 1, 2, 3

)

select p.snapshot_quarter, p.pf_code, p.forecast_quarter
from {{ ref('fct_product_volume_at_risk') }} p
full join expected e
    on  e.snapshot_quarter = p.snapshot_quarter
    and e.pf_code = p.pf_code
    and e.forecast_quarter = p.forecast_quarter
where p.pf_code is null
   or e.pf_code is null
   or p.units_at_risk_baseline <> e.units_at_risk_baseline
   or p.units_at_risk_stretch  <> e.units_at_risk_stretch
   or abs(p.revenue_at_risk_baseline - p.units_at_risk_baseline * p.price_eur_per_unit) > 0.01
   or (p.has_price and p.revenue_at_risk_baseline is null)
   or (not p.has_price and p.revenue_at_risk_baseline is not null)
