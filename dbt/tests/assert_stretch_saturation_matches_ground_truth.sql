-- Stretch saturation must match the planted truth (catches the unqualified-CM trap).
-- Returns rows only where the mart is missing a row or is off by more than 0.005.

select
    g.snapshot_quarter,
    g.ac_code,
    g.quarter,
    g.stretch_saturation::numeric as expected,
    m.stretch_saturation          as actual
from {{ source('ground_truth', 'saturation') }} g
left join {{ ref('fct_saturation') }} m
    on  m.snapshot_quarter = g.snapshot_quarter
    and m.ac_code = g.ac_code
    and m.forecast_quarter = g.quarter
where m.ac_code is null
   or abs(m.stretch_saturation - g.stretch_saturation::numeric) > 0.005
