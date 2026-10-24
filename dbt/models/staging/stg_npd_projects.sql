-- Launch pipeline: BOMs of new products (NPD) that are not in the plant BOM yet.
-- Grain: snapshot_quarter x pf_code x ac_code.

select
    snapshot_quarter,
    trim(project)                       as project_id,
    {{ clean_code('pf_code') }}         as pf_code,
    nullif(trim(pf_description), '')    as pf_description,
    trim(launch_quarter)                as launch_quarter,
    {{ clean_code('ac_code') }}         as ac_code,
    nullif(trim(ac_description), '')    as ac_description,
    {{ to_numeric('qty_per_pf') }}      as qty_per_pf,
    {{ to_bool('new_component') }}      as is_new_component
from {{ source('raw', 'npd_projects') }}
