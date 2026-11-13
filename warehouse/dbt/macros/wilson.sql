{#
  Wilson score interval for a proportion (95% by default).
  Better than "p +/- 1.96*sqrt(p(1-p)/n)" for small groups like 40 games per genre,
  and it never goes below 0% or above 100%.
#}
{% macro wilson_low(k, n, z=1.96) -%}
    case when {{ n }} = 0 then null else
    ((
        ({{ k }}::numeric / {{ n }}) + ({{ z }}^2) / (2 * {{ n }})
        - {{ z }} * sqrt( ({{ k }}::numeric / {{ n }}) * (1 - {{ k }}::numeric / {{ n }}) / {{ n }} + ({{ z }}^2) / (4 * {{ n }}^2) )
    ) / (1 + ({{ z }}^2) / {{ n }})) ::numeric end
{%- endmacro %}

{% macro wilson_high(k, n, z=1.96) -%}
    case when {{ n }} = 0 then null else
    ((
        ({{ k }}::numeric / {{ n }}) + ({{ z }}^2) / (2 * {{ n }})
        + {{ z }} * sqrt( ({{ k }}::numeric / {{ n }}) * (1 - {{ k }}::numeric / {{ n }}) / {{ n }} + ({{ z }}^2) / (4 * {{ n }}^2) )
    ) / (1 + ({{ z }}^2) / {{ n }})) ::numeric end
{%- endmacro %}
