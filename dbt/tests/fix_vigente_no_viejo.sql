-- Falla si algún día usa un FIX de hace más de 5 días. El hueco más largo
-- normal es Semana Santa (jueves y viernes feriados + fin de semana = 4 días).
-- Si esto falla, probablemente la ingesta de Banxico dejó de traer datos.
select *
from {{ ref('int_fix_diario') }}
where fecha >= '2020-01-02'
  and dias_desde_fix > 5
