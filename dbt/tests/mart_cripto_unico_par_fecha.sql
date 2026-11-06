select par, fecha, count(*) as n
from {{ ref('mart_cripto_diario') }}
group by 1, 2
having count(*) > 1
