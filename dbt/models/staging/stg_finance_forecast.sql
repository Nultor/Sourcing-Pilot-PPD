-- Quarterly demand forecast per finished product (PF), two scenarios.
-- Grain: snapshot_quarter x pf_code x forecast_quarter.

with source as (

    select
        snapshot_quarter,
        {{ clean_code('pf') }}            as pf_code,
        trim(quarter)                     as forecast_quarter,
        {{ to_numeric('qty_baseline') }}  as qty_baseline,
        {{ to_numeric('qty_stretch') }}   as qty_stretch,
        trim(forecast_version)            as forecast_version
    from {{ source('raw', 'finance_forecast') }}

),

-- Finance builds the stretch scenario as a fixed uplift on baseline per PF,
-- so a blank stretch value is filled with baseline x that PF's uplift.
pf_uplift as (

    select
        snapshot_quarter,
        pf_code,
        avg(qty_stretch / nullif(qty_baseline, 0)) as stretch_uplift
    from source
    group by 1, 2

)

select
    s.snapshot_quarter,
    s.pf_code,
    s.forecast_quarter,
    s.qty_baseline,
    coalesce(s.qty_stretch, round(s.qty_baseline * u.stretch_uplift)) as qty_stretch,
    s.qty_stretch is null                                             as is_stretch_imputed,
    s.forecast_version
from source s
left join pf_uplift u
    on  u.snapshot_quarter = s.snapshot_quarter
    and u.pf_code = s.pf_code
