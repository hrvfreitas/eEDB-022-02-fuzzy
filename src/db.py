"""
Conexão com o PostgreSQL.

Centraliza a criação da engine SQLAlchemy usada por todas as etapas
do pipeline (RAW -> Trusted -> Delivery).

Os valores podem ser sobrescritos por variáveis de ambiente -- é assim que
o container Python (subido pelo Terraform) se conecta ao container do
Postgres pelo nome do serviço na rede Docker (DB_HOST=postgres). Quando
rodado fora do Docker (direto na máquina host), os defaults abaixo
(localhost) continuam funcionando normalmente.
"""
import os
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "case_dados")

CONN_STRING = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def get_engine():
    """Retorna uma engine SQLAlchemy conectada ao banco relacional do projeto."""
    return create_engine(CONN_STRING)


def wait_for_db(max_tentativas: int = 30, intervalo_segundos: float = 2.0):
    """Aguarda o Postgres ficar pronto para aceitar conexões.

    Útil quando  roda dentro do container Python e o container do
    Postgres ainda está inicializando.
    """
    engine = get_engine()
    for tentativa in range(1, max_tentativas + 1):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            print(f"Conectado ao Postgres em {DB_HOST}:{DB_PORT}/{DB_NAME}.")
            return
        except OperationalError:
            print(
                f"Postgres ainda não disponível em {DB_HOST}:{DB_PORT} "
                f"(tentativa {tentativa}/{max_tentativas})..."
            )
            time.sleep(intervalo_segundos)
    raise RuntimeError(
        f"Não foi possível conectar ao Postgres em {DB_HOST}:{DB_PORT} "
        f"após {max_tentativas} tentativas."
    )
