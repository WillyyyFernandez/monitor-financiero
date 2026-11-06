-- Falla si hay más de una fila por serie y fecha.
select id_serie, fecha, count(*) as n
from {{ ref('stg_banxico_series') }}
group by 1, 2
having count(*) > 1
