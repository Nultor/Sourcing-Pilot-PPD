-- dim_product must match ground_truth.products on every product of every snapshot.
-- Returns rows only where a product is missing on one side or a value differs.
-- The ground truth is loaded as text: 'True'/'False', '500', and '' for empty.

select
    coalesce(d.snapshot_quarter, g.snapshot_quarter) as snapshot_quarter,
    coalesce(d.pf_code, g.pf_code)                   as pf_code,
    g.brand          as expected_brand,          d.brand          as actual_brand,
    g.format_ml      as expected_format_ml,      d.format_ml      as actual_format_ml,
    g.is_hero        as expected_is_hero,        d.is_hero        as actual_is_hero,
    g.is_npd         as expected_is_npd,         d.is_npd         as actual_is_npd,
    g.launch_quarter as expected_launch_quarter, d.launch_quarter as actual_launch_quarter
from {{ ref('dim_product') }} d
full join {{ source('ground_truth', 'products') }} g     -- full join: catches missing rows on both sides
    on  g.snapshot_quarter = d.snapshot_quarter
    and g.pf_code = d.pf_code
where d.pf_code is null
   or g.pf_code is null
   or d.brand is distinct from nullif(g.brand, '')
   or d.format_ml is distinct from nullif(g.format_ml, '')::numeric
   or d.is_hero is distinct from (g.is_hero = 'True')
   or d.is_npd is distinct from (g.is_npd = 'True')
   or d.launch_quarter is distinct from nullif(g.launch_quarter, '')
   or lower(d.pf_description) is distinct from lower(g.pf_description)   -- only the case differs
