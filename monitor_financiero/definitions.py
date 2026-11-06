import sys
from pathlib import Path

from dagster import AssetKey, DefaultScheduleStatus, MaterializeResult, in_process_executor, AssetSelection, Definitions, ScheduleDefinition, asset, define_asset_job
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets
from dotenv import load_dotenv

from ingesta import banxico, binance

RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")

DBT_DIR = RAIZ / "dbt"
dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()


# Las claves coinciden con source('bronze', ...) de dbt, así Dagster dibuja cada
# ingesta como padre de su modelo de staging.
@asset(key=AssetKey(["bronze", "banxico_series"]), group_name="ingesta")
def banxico_series(context):
    resumen = banxico.sincronizar()
    context.log.info(f"bronze banxico: {resumen}")
    return MaterializeResult(metadata={"filas": resumen["filas"], "archivo": resumen["archivo"]})


@asset(key=AssetKey(["bronze", "binance_klines"]), group_name="ingesta")
def binance_klines(context):
    resumen = binance.sincronizar()
    context.log.info(f"velas descargadas por par: {resumen}")
    return MaterializeResult(metadata={"velas_descargadas": sum(resumen.values())})


@dbt_assets(manifest=dbt_project.manifest_path)
def dbt_models(context, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


job_diario = define_asset_job("pipeline_diario", selection=AssetSelection.all())
programacion_diaria = ScheduleDefinition(
    job=job_diario, cron_schedule="0 7 * * *", execution_timezone="America/Mexico_City",
    default_status=DefaultScheduleStatus.RUNNING,  # activa sin tocar la interfaz
)

defs = Definitions(
    assets=[banxico_series, binance_klines, dbt_models],
    jobs=[job_diario],
    executor=in_process_executor,  # DuckDB admite un solo escritor a la vez
    schedules=[programacion_diaria],
    resources={
        "dbt": DbtCliResource(
            project_dir=dbt_project,
            dbt_executable=str(Path(sys.executable).parent / "dbt"),
        )
    },
)
