-- Reusable cleaning snippets for the staging layer.

-- Codes (AC, PF): trim spaces, drop a trailing ".0" left by Excel, uppercase, blank -> null.
--   ' E73023'     -> 'E73023'
--   '366287809.0' -> '366287809'
{% macro clean_code(col) -%}
    nullif(upper(regexp_replace(trim({{ col }}), '\.0+$', '')), '')
{%- endmacro %}

-- Numbers stored as text: trim, blank -> null, cast.
{% macro to_numeric(col) -%}
    nullif(trim({{ col }}), '')::numeric
{%- endmacro %}

-- Yes/no flags written in many ways (Y, yes, N, no, ...) -> boolean, anything else -> null.
{% macro to_bool(col) -%}
    case
        when lower(trim({{ col }})) in ('y', 'yes', 'true', '1') then true
        when lower(trim({{ col }})) in ('n', 'no', 'false', '0') then false
    end
{%- endmacro %}

-- Join key for the supplier_alias_map seed: case and surrounding spaces don't matter.
{% macro supplier_key(col) -%}
    nullif(lower(trim({{ col }})), '')
{%- endmacro %}
