-- Component (AC) dimension: what each component is and what role it plays.
-- Grain: snapshot_quarter x ac_code.
--
-- All attributes come from int_component_enriched (component master with the missing
-- brand / material / size recovered). On top of that:
--   n_products_using  how many products (PFs, on sale or in launch) use the component
--   used_by_hero      true if at least one of those products is a hero (business driver)
--   is_new            true if it is a new component for a launch (NPD)

-- usage: who uses each component (a CTE = a named step of the query)
with usage as (

    select
        b.snapshot_quarter,
        b.ac_code,
        count(distinct b.pf_code) as n_products_using,
        bool_or(p.is_hero)        as used_by_hero
    from {{ ref('int_bom') }} b
    join {{ ref('dim_product') }} p
        on  p.snapshot_quarter = b.snapshot_quarter
        and p.pf_code = b.pf_code
    group by b.snapshot_quarter, b.ac_code

),

-- npd_projects is a BOM (one row per launch product x component): one row per component
npd as (

    select
        snapshot_quarter,
        ac_code,
        bool_or(is_new_component) as is_new
    from {{ ref('stg_npd_projects') }}
    group by snapshot_quarter, ac_code

)

select
    c.snapshot_quarter || '|' || c.ac_code  as component_key,
    c.snapshot_quarter,
    c.ac_code,
    c.ac_description,
    c.family,
    c.material,
    c.size_ml,
    c.neck,
    c.colour,
    c.weight_g,
    c.technology,
    c.brand,
    c.status,
    c.is_brand_specific,
    c.is_sized,
    c.is_brand_recovered,
    c.is_material_recovered,
    c.material_source,
    c.is_size_recovered,
    -- left joins: a component that no product uses / that isn't in NPD gets 0 / false, not null
    coalesce(u.n_products_using, 0)         as n_products_using,
    coalesce(u.used_by_hero, false)         as used_by_hero,
    coalesce(n.is_new, false)               as is_new
from {{ ref('int_component_enriched') }} c
left join usage u
    on  u.snapshot_quarter = c.snapshot_quarter
    and u.ac_code = c.ac_code
left join npd n
    on  n.snapshot_quarter = c.snapshot_quarter
    and n.ac_code = c.ac_code
