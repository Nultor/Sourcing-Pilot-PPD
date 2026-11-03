-- Quarter labels like '2027Q1' as a running number, so quarters can be subtracted.
--   quarter_number('2027Q1') - quarter_number('2026Q4') = 1
{% macro quarter_number(col) -%}
    (left({{ col }}, 4)::int * 4 + right({{ col }}, 1)::int)
{%- endmacro %}
