select par, fecha, count(*) as n
from {{ ref('stg_binance_klines') }}
group by 1, 2
having count(*) > 1
