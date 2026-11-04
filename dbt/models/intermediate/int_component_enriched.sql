-- Component (AC) master data with the values missing by mistake recovered from other sources.
-- Grain: snapshot_quarter x ac_code.
--
-- Most blanks in component_master are correct: only some families carry a brand (printed
-- with brand artwork) or a size (seeds/component_families.csv). A blank is only filled
-- where the family should have the value, and only when the other source gives one answer:
--   brand     AC -> products (int_bom) -> dim_product.brand       brand-specific families
--   size_ml   1. AC -> products (int_bom) -> dim_product.format_ml sized families
--             2. the size at the end of the description          sized families
--   material  1. site_bom_moq.material of the AC (same snapshot)  any family
--             2. the description 'Jar glass 500ml'                  families without a brand
--             3. the last known material in an earlier snapshot    any family
-- is_*_recovered flags which values were filled in; material_source says where the material came from.

{#- the text between the family name and the last word (the size or neck) -#}
{%- set material_from_description -%}
nullif(trim(regexp_replace(substr(c.ac_description, length(c.family) + 2), '\s+\S+$', '')), '')
{%- endset %}

{#- the size at the end of the description in ml: 'Jar glass 500ml' -> 500, '1,5 L' -> 1500 -#}
{%- set size_from_description -%}
(regexp_match(lower(replace(c.ac_description, ',', '.')), '([0-9.]+)\s*(ml|l)$'))[1]::numeric
    * case (regexp_match(lower(replace(c.ac_description, ',', '.')), '([0-9.]+)\s*(ml|l)$'))[2]
        when 'l' then 1000 else 1 end
{%- endset %}

with component as (

    select * from {{ ref('stg_component_master') }}

),

families as (

    select * from {{ ref('component_families') }}

),

-- brand and format of the products that use each component
product_attributes as (

    select
        b.snapshot_quarter,
        b.ac_code,
        count(distinct p.brand)     as n_brands,
        min(p.brand)                as brand,
        count(distinct p.format_ml) as n_formats,
        min(p.format_ml)            as format_ml
    from {{ ref('int_bom') }} b
    join {{ ref('dim_product') }} p
        on  p.snapshot_quarter = b.snapshot_quarter
        and p.pf_code = b.pf_code
    group by 1, 2

),

bom_material as (

    select
        snapshot_quarter,
        ac_code,
        count(distinct material) as n_materials,
        min(material)            as material
    from {{ ref('stg_site_bom_moq') }}
    where material is not null
    group by 1, 2

),

-- every material ever recorded for an AC, per snapshot, from either source
material_history as (

    select snapshot_quarter, ac_code, material
    from component
    where material is not null

    union

    select snapshot_quarter, ac_code, material
    from bom_material
    where n_materials = 1

),

-- the most recent material from an EARLIER snapshot (never a later one: that would
-- use information the business didn't have yet). Materials don't change between
-- snapshots for the same AC, so the last known value is safe to carry forward.
previous_material as (

    select distinct on (c.snapshot_quarter, c.ac_code)
        c.snapshot_quarter,
        c.ac_code,
        h.material
    from component c
    join material_history h
        on  h.ac_code = c.ac_code
        and {{ quarter_number('h.snapshot_quarter') }} < {{ quarter_number('c.snapshot_quarter') }}
    order by c.snapshot_quarter, c.ac_code, h.snapshot_quarter desc, h.material

),

recovered as (

    select
        c.*,
        coalesce(f.is_brand_specific, false) as is_brand_specific,
        coalesce(f.is_sized, false)          as is_sized,
        case when c.brand is null and f.is_brand_specific and pa.n_brands = 1
             then pa.brand end               as brand_recovered,
        -- size: only for sized families. Labels and cartons also end in '500ml', but
        -- that is the product they are printed for, not the size of the label itself.
        case when c.size_ml is null and f.is_sized
             then coalesce(
                    case when pa.n_formats = 1 then pa.format_ml end,
                    {{ size_from_description }}
                  ) end                      as size_recovered,
        -- material: first source that has it, same snapshot before older snapshots
        case
            when c.material is not null then 'component_master'
            when m.n_materials = 1 then 'site_bom_moq'
            -- families without brand artwork are named '<family> <material> <size>':
            -- 'Jar glass 500ml', 'Pump multi-material 20/400'
            when not f.is_brand_specific
             and {{ material_from_description }} is not null then 'description'
            when pm.material is not null then 'previous_snapshot'
        end                                  as material_source,
        case
            when c.material is not null then null
            when m.n_materials = 1 then m.material
            when not f.is_brand_specific then coalesce({{ material_from_description }}, pm.material)
            else pm.material
        end                                  as material_recovered
    from component c
    left join families f
        on f.family = c.family
    left join product_attributes pa
        on  pa.snapshot_quarter = c.snapshot_quarter
        and pa.ac_code = c.ac_code
    left join bom_material m
        on  m.snapshot_quarter = c.snapshot_quarter
        and m.ac_code = c.ac_code
    left join previous_material pm
        on  pm.snapshot_quarter = c.snapshot_quarter
        and pm.ac_code = c.ac_code

)

select
    snapshot_quarter,
    ac_code,
    ac_description,
    family,
    is_brand_specific,
    is_sized,
    coalesce(material, material_recovered) as material,
    coalesce(size_ml, size_recovered)      as size_ml,
    neck,
    colour,
    weight_g,
    technology,
    coalesce(brand, brand_recovered)       as brand,
    status,
    brand_recovered is not null            as is_brand_recovered,
    material_recovered is not null         as is_material_recovered,
    material_source,
    size_recovered is not null             as is_size_recovered
from recovered
