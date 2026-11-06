-- CETES 28d es un promedio mensual: se conoce al cierre del mes.
select
    fecha                        as mes,
    fecha + interval 1 month     as disponible_desde,
    valor                        as cetes_28_pct
from {{ ref('stg_banxico_series') }}
where serie = 'cetes_28_dias'
