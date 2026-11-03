-- Severity and first breach quarter must match every planted case.
-- Returns rows only where the mart is missing a case or labels it differently.

select
    g.snapshot_quarter,
    g.ac_code,
    g.case,
    g.severity                as expected_severity,
    m.severity                as actual_severity,
    g.first_breach_quarter    as expected_first_breach,
    m.first_breach_quarter    as actual_first_breach
from {{ source('ground_truth', 'planted_cases') }} g
left join {{ ref('fct_quarters_to_breach') }} m
    on  m.snapshot_quarter = g.snapshot_quarter
    and m.ac_code = g.ac_code
where m.ac_code is null
   or m.severity <> g.severity
   or m.first_breach_quarter is distinct from nullif(g.first_breach_quarter, '')
