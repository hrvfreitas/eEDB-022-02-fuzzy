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
import os                     # Para ler variáveis de ambiente
import time                   # Para pausar entre tentativas de conexão

from sqlalchemy import create_engine   # Cria a engine de conexão com o banco
from sqlalchemy.exc import OperationalError   # Exceção levantada quando o banco não está acessível

# Lê as configurações do banco de variáveis de ambiente ou usa valores padrão (localhost)
DB_USER = os.environ.get("DB_USER", "postgres")          # Usuário padrão: postgres
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")  # Senha padrão: postgres
DB_HOST = os.environ.get("DB_HOST", "localhost")         # Host padrão: localhost (fora do Docker)
DB_PORT = os.environ.get("DB_PORT", "5432")              # Porta padrão do PostgreSQL: 5432
DB_NAME = os.environ.get("DB_NAME", "case_dados")        # Nome do banco padrão: case_dados

# Monta a string de conexão no formato PostgreSQL+psycopg2 (driver Python)
CONN_STRING = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def get_engine():
    """
    Retorna uma engine SQLAlchemy conectada ao banco relacional do projeto.
    A engine é o objeto que gerencia a conexão e execução de comandos SQL.
    """
    return create_engine(CONN_STRING)


def wait_for_db(max_tentativas: int = 30, intervalo_segundos: float = 2.0):
    """
    Aguarda o Postgres ficar pronto para aceitar conexões.

    Útil quando roda dentro do container Python e o container do
    Postgres ainda está inicializando.
    Parâmetros:
        max_tentativas: número máximo de tentativas de conexão (padrão: 30)
        intervalo_segundos: tempo de espera entre tentativas (padrão: 2 segundos)
    Levanta RuntimeError se não conseguir conectar após as tentativas.
    """
    # Cria a engine (usa as variáveis de ambiente ou defaults)
    engine = get_engine()
    # Loop de tentativas
    for tentativa in range(1, max_tentativas + 1):
        try:
            # Tenta abrir uma conexão e executar um comando simples (SELECT 1)
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            # Se chegou aqui, a conexão foi bem-sucedida
            print(f"Conectado ao Postgres em {DB_HOST}:{DB_PORT}/{DB_NAME}.")
            return   # Sai da função com sucesso
        except OperationalError:
            # Se o banco ainda não está disponível, imprime mensagem e espera
            print(
                f"Postgres ainda não disponível em {DB_HOST}:{DB_PORT} "
                f"(tentativa {tentativa}/{max_tentativas})..."
            )
            # Aguarda o intervalo antes da próxima tentativa
            time.sleep(intervalo_segundos)
    # Se saiu do loop sem conectar, levanta erro
    raise RuntimeError(
        f"Não foi possível conectar ao Postgres em {DB_HOST}:{DB_PORT} "
        f"após {max_tentativas} tentativas."
    )
