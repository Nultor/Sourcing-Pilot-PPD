-- Component (AC) master data.
-- Grain: snapshot_quarter x ac_code.

select
    snapshot_quarter,
    {{ clean_code('ac_code') }}        as ac_code,
    nullif(trim(description), '')      as ac_description,
    nullif(trim(family), '')           as family,
    nullif(trim(material), '')         as material,
    {{ to_numeric('size_ml') }}        as size_ml,
    nullif(trim(neck), '')             as neck,
    nullif(lower(trim(colour)), '')    as colour,
    {{ to_numeric('weight_g') }}       as weight_g,
    nullif(trim(technology), '')       as technology,
    nullif(trim(brand), '')            as brand,
    nullif(lower(trim(status)), '')    as status
from {{ source('raw', 'component_master') }}
