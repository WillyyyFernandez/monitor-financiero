-- Frescura de las series MENSUALES de Banxico. INEGI publica el INPC de un mes
-- alrededor del día 9 del mes siguiente, así que lo normal es que el último dato
-- tenga hasta ~70 días (p. ej. el 8 de noviembre el último INPC es de septiembre).
-- Más de 80 días indica que la serie dejó de actualizarse.
-- El FIX y la TIIE diarios ya los cubre fix_vigente_no_viejo.
{{ config(severity='warn') }}

select serie, max(fecha) as ultimo_dato
from {{ ref('stg_banxico_series') }}
where serie in ('inpc_indice_general', 'cetes_28_dias')
group by serie
having max(fecha) < {{ var('fecha_referencia', 'current_date') }} - 80
