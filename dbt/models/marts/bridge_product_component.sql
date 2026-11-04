-- Which products (PF) use which components (AC): the BOM as a mart, so Cube can link
-- components to products. Grain: snapshot_quarter x pf_code x ac_code.
--
-- A product uses many components and a component is used by many products, so neither
-- dimension can hold the other: this bridge sits between dim_product and dim_component.
-- It covers products on sale (site BOM) and launches (NPD BOM), see int_bom.

select
    snapshot_quarter || '|' || pf_code || '|' || ac_code as bom_key,
    snapshot_quarter,
    pf_code,
    ac_code,
    qty_per_pf,
    bom_source
from {{ ref('int_bom') }}
