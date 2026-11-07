# Monitor financiero de México

Pipeline de datos de punta a punta: ingesta diaria de Banxico (tipo de cambio FIX,
TIIE, CETES, INPC) y Binance (BTC, ETH, USDT en dólares y pesos), modelado con dbt
sobre DuckDB y orquestación con Dagster.

```
                      bronze (Parquet inmutable)     staging (dbt)          marts (dbt)
Banxico SIE ──► data/bronze/banxico_series/ ──► stg_banxico_series ─ int_* ─ mart_indicadores_diarios
Binance     ──► data/bronze/binance_klines/ ──► stg_binance_klines ──────── mart_cripto_diario
```

Cada descarga se guarda como un Parquet nuevo en
`data/bronze/<fuente>/fecha_carga=AAAA-MM-DD/`, y nunca se reescribe. Staging se
queda con la versión más reciente de cada dato, así una revisión de Banxico
reemplaza al valor viejo sin perder el historial de lo que se publicó.

## Estructura

| Carpeta | Contenido |
|---|---|
| `ingesta/` | Descarga a bronze (Banxico completo, Binance incremental) y reintentos HTTP |
| `dbt/` | Modelos `staging`, `intermediate`, `marts` y tests de calidad |
| `monitor_financiero/` | Definiciones de Dagster: activos, trabajo y programación diaria (13:00 CDMX, después del FIX del día) |
| `docker/` | Configuración de la instancia de Dagster para el contenedor |

## Requisitos

- Token del [SIE de Banxico](https://www.banxico.org.mx/SieAPIRest/service/v1/token) (gratis).
- Binance no requiere llave.

Copia `.env.example` a `.env` y rellena los tokens. `.env` nunca se sube a git.

## Correr con Docker (servidor)

```bash
cp .env.example .env        # y rellena BANXICO_TOKEN
docker compose up -d --build
docker compose ps
```

- Interfaz de Dagster: `http://127.0.0.1:3000` en la propia máquina. Solo escucha en
  localhost; desde otra computadora usa un túnel SSH:
  `ssh -L 3000:127.0.0.1:3000 usuario@servidor`.
- La programación diaria queda activa al arrancar; el daemon la dispara solo.
- Las corridas se ejecutan de una en una (DuckDB admite un solo escritor).
- Los datos y el historial de Dagster viven en los volúmenes `datos` y `estado`.

Primera carga sin esperar a las 13:00:

```bash
docker compose exec webserver dagster job launch -m monitor_financiero.definitions -j pipeline_diario
```

Copiar la base de datos fuera del contenedor (respaldo o evidencia):

```bash
docker compose cp webserver:/app/data/monitor.duckdb ./monitor.duckdb
```

## Calidad y frescura

- `dbt build` corre 43 tests: unicidad, nulos, valores permitidos, rangos
  plausibles, y frescura de los **datos** (la última vela de cada par tiene como
  mucho 2 días; INPC y CETES, como mucho 80). Los de frescura son de severidad
  `warn`: avisan sin detener el pipeline.
- `dbt source freshness` revisa la frescura de la **carga**: más de 26 h sin
  descarga es aviso y más de 50 h es error.
- Dagster corre esa revisión en el trabajo `revision_frescura` todos los días a
  las 20:00 CDMX, lejos de la corrida de las 13:00. Si la corrida diaria no ocurrió
  (máquina apagada, daemon caído), la revisión queda en rojo.

## Agente en lenguaje natural

Un modelo local (Qwen2.5-14B en `llama-server`, CPU) responde preguntas en
español sobre los marts. El modelo **no escribe SQL**: elige una de seis funciones
de `agente/funciones.py` (último dato, resumen de un periodo, tasa real de un mes,
cripto, prima cripto vs FIX, cobertura) y nosotros ejecutamos la consulta
parametrizada, en solo lectura.

- Terminal: `docker compose exec webserver python -m agente.chat "¿Cuánto subió el dólar en octubre de 2026?"`
- Web: servicio `chat` en `http://127.0.0.1:8501` (Streamlit). Muestra qué
  función llamó el modelo y el resultado exacto que usó.

Configuración (la llave nunca va al repo ni a `.env`): `LLM_BASE_URL`,
`LLM_MODEL` y `LLM_API_KEY_FILE`. En la máquina con el modelo, un
`docker-compose.override.yml` local monta el archivo de la llave:

```yaml
services:
  webserver:
    environment:
      LLM_BASE_URL: http://172.17.0.1:8081/v1
      LLM_MODEL: osint-local
      LLM_API_KEY_FILE: /run/secrets/llama-api.key
    volumes:
      - /ruta/a/llama-api.key:/run/secrets/llama-api.key:ro
  chat:
    volumes:
      - /ruta/a/llama-api.key:/run/secrets/llama-api.key:ro
```

Evaluación con 6 preguntas (Qwen2.5-14B, 16 hilos de CPU): 6/6 correctas,
incluida una sin datos (dogecoin) donde el modelo dijo que no podía responder;
de 13 a 64 s por respuesta.

## Integración continua

`.github/workflows/ci.yml` corre en cada push y pull request a `main`:

1. `dbt build` (modelos y 43 tests) sobre datos de muestra fijos en
   `ci/fixtures/bronze/` (enero 2024 a marzo 2025, datos públicos). No usa red ni
   tokens: prueba el código, no las APIs.
2. Validación de las definiciones de Dagster.
3. Construcción de la imagen de Docker.

Los tests que dependen de la fecha usan `--vars fecha_referencia` para que la
muestra no "envejezca". Si cambia el esquema de bronze, regenera la muestra con
`python scripts/generar_fixtures_ci.py`.

Si cambias `.env`, recrea los contenedores (`docker restart` no relee el archivo):

```bash
docker compose up -d --force-recreate
```

## Correr en local (desarrollo)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DAGSTER_HOME=$PWD/.dagster && mkdir -p .dagster && touch .dagster/dagster.yaml
(cd dbt && ../.venv/bin/dbt parse)   # regenera el manifest que lee Dagster
.venv/bin/dagster asset materialize -m monitor_financiero.definitions --select '*'
.venv/bin/dagster dev -m monitor_financiero.definitions   # interfaz en 127.0.0.1:3000
```

Después de agregar o cambiar modelos o tests de dbt, corre `dbt parse` antes de
`dagster asset materialize`: ese comando usa el manifest existente y falla con
`KeyError` si no conoce un nodo nuevo. `dagster dev` y la imagen de Docker lo
regeneran solos.
