-- dim_component must match ground_truth.components (brand, material, size, is_new) and the
-- ground-truth BOM + products (n_products_using, used_by_hero), every component of every snapshot.
-- Returns rows only where a component is missing on one side or a value differs.
-- Guards the recovery rules in int_component_enriched, including the brand trap.
-- The ground truth is loaded as text: 'True'/'False', '500', and '' for empty.

with truth_usage as (

    select
        b.snapshot_quarter,
        b.ac_code,
        count(distinct b.pf_code) as n_products_using,
        bool_or(p.is_hero = 'True') as used_by_hero
    from {{ source('ground_truth', 'bom') }} b
    join {{ source('ground_truth', 'products') }} p
        on  p.snapshot_quarter = b.snapshot_quarter
        and p.pf_code = b.pf_code
    group by 1, 2

)

select
    coalesce(d.snapshot_quarter, g.snapshot_quarter) as snapshot_quarter,
    coalesce(d.ac_code, g.ac_code)                   as ac_code,
    g.brand          as expected_brand,          d.brand            as actual_brand,
    g.material       as expected_material,       d.material         as actual_material,
    g.size_ml        as expected_size_ml,        d.size_ml          as actual_size_ml,
    g.is_new         as expected_is_new,         d.is_new           as actual_is_new,
    u.n_products_using as expected_n_products,   d.n_products_using as actual_n_products,
    u.used_by_hero   as expected_used_by_hero,   d.used_by_hero     as actual_used_by_hero
from {{ ref('dim_component') }} d
full join {{ source('ground_truth', 'components') }} g
    on  g.snapshot_quarter = d.snapshot_quarter
    and g.ac_code = d.ac_code
left join truth_usage u
    on  u.snapshot_quarter = g.snapshot_quarter
    and u.ac_code = g.ac_code
where d.ac_code is null
   or g.ac_code is null
   or d.brand is distinct from nullif(g.brand, '')
   or d.material is distinct from nullif(g.material, '')
   or d.size_ml is distinct from nullif(g.size_ml, '')::numeric
   or d.is_new is distinct from (g.is_new = 'True')
   or d.n_products_using is distinct from coalesce(u.n_products_using, 0)
   or d.used_by_hero is distinct from coalesce(u.used_by_hero, false)
