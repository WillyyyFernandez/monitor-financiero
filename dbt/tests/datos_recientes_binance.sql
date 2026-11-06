-- Frescura de los DATOS (no de la descarga): cada par debe tener una vela cerrada
-- de hace como mucho 2 días. Si la ingesta "funciona" pero Binance devuelve datos
-- viejos o un par deja de cotizar, este test lo detecta.
-- Severidad warn: avisa en Dagster sin detener el resto del pipeline.
-- fecha_referencia permite probar el test con otra fecha (--vars).
{{ config(severity='warn') }}

select par, max(fecha) as ultima_vela
from {{ ref('mart_cripto_diario') }}
group by par
having max(fecha) < {{ var('fecha_referencia', 'current_date') }} - 2
