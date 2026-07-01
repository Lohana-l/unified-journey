{#
    Override dbt's default schema concat (target.schema + '_' + custom_schema)
    with the model's custom_schema literal. This keeps schema names clean:
    `staging`, `intermediate`, `marts` instead of `dev_staging`, `dev_intermediate`, …
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
