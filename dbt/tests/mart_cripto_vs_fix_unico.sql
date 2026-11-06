select fecha, activo, count(*) as n
from {{ ref('mart_cripto_vs_fix') }}
group by 1, 2
having count(*) > 1
