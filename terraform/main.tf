# Este Terraform substitui os passos manuais do README:
#   service postgresql start
#   psql -U postgres -f setup_database.sql
#   cd src && python3 run_all.py
#
# Ele sobe DOIS containers Docker, na mesma rede:
#   1) "postgres" - banco de dados relacional do projeto (cria o database
#      "case_dados"; os schemas raw/trusted/delivery continuam sendo
#      criados pelos próprios scripts Python).
#   2) "python"   - imagem construída a partir do Dockerfile do projeto,
#      que roda o pipeline completo (run_all.py: 01_ingest_raw.py ->
#      02_trusted.py -> 03_delivery.py) conectando no Postgres pela rede
#      Docker interna (host "postgres").

# --------------------------------------------------------------------------
# Rede compartilhada pelos dois containers
# --------------------------------------------------------------------------

# Cria uma rede Docker interna chamada 'case_dados' (nome definido em var.network_name)
# para que os containers possam se comunicar entre si pelo nome do container.
resource "docker_network" "case_dados" {
  name = var.network_name
}

# --------------------------------------------------------------------------
# Container 1: PostgreSQL
# --------------------------------------------------------------------------

# Baixa a imagem oficial do PostgreSQL (var.postgres_image, ex: "postgres:13")
resource "docker_image" "postgres" {
  name         = var.postgres_image
  keep_locally = true   # Mantém a imagem localmente mesmo após o destroy
}

# Cria um volume Docker persistente para armazenar os dados do PostgreSQL
# (evita perda de dados ao recriar o container)
resource "docker_volume" "pgdata" {
  name = var.data_volume_name
}

# Define o container PostgreSQL
resource "docker_container" "postgres" {
  name  = var.postgres_container_name   # Nome do container (ex: "case_dados_postgres")
  image = docker_image.postgres.image_id   # Referência à imagem baixada acima

  # Conecta o container à rede 'case_dados' com o alias "postgres"
  # Assim o container Python pode acessar o banco via "postgres" (DB_HOST=postgres)
  networks_advanced {
    name    = docker_network.case_dados.name
    aliases = ["postgres"]
  }

  # Define as variáveis de ambiente para criar o usuário admin do PostgreSQL
  env = [
    "POSTGRES_USER=${var.db_admin_user}",
    "POSTGRES_PASSWORD=${var.db_admin_password}",
  ]

  # Mapeia a porta 5432 do container para a porta definida em var.db_port
  # na máquina host, para acesso externo (psql, DBeaver, etc.)
  ports {
    internal = 5432
    external = var.db_port
  }

  # Monta o volume persistente no diretório de dados do PostgreSQL
  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }

  # Define um health check usando pg_isready para verificar se o banco está aceitando conexões
  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U ${var.db_admin_user}"]
    interval = "5s"    # Verifica a cada 5 segundos
    timeout  = "3s"    # Tempo máximo para cada verificação
    retries  = 10      # Número de tentativas antes de considerar o container unhealthy
  }

  # Aguarda o container ficar saudável (wait=true) e garante que ele permaneça em execução
  wait     = true
  must_run = true
}

# Aguarda alguns segundos após o container PostgreSQL estar pronto
# para garantir que o provider PostgreSQL possa se conectar sem problemas.
resource "time_sleep" "wait_for_postgres" {
  depends_on      = [docker_container.postgres]
  create_duration = "8s"
}

# Utiliza o provider postgresql (definido em outro arquivo) para criar o banco de dados
# "case_dados" (var.db_name) dentro do PostgreSQL, com o usuário admin como proprietário.
resource "postgresql_database" "case_dados" {
  name  = var.db_name
  owner = var.db_admin_user

  depends_on = [time_sleep.wait_for_postgres]
}

# --------------------------------------------------------------------------
# Container 2: Python (pipeline)
# --------------------------------------------------------------------------

# Constrói a imagem Docker para a aplicação Python a partir do Dockerfile
# localizado no caminho var.project_path (ex: ".")
resource "docker_image" "python_app" {
  name = var.python_image_name   # Nome da imagem (ex: "case_dados_python:latest")

  build {
    context    = var.project_path           # Diretório onde está o Dockerfile
    dockerfile = "Dockerfile"               # Nome do Dockerfile
  }

  # Gatilhos para reconstruir a imagem sempre que o código-fonte mudar.
  # O Terraform recalcula os hashes e, se algum mudar, a imagem é reconstruída.
  triggers = {
    dockerfile_sha1   = filesha1("${var.project_path}/Dockerfile")
    requirements_sha1 = filesha1("${var.project_path}/requirements.txt")
    src_dir_sha1      = sha1(join("", [for f in fileset("${var.project_path}/src", "**") : filesha1("${var.project_path}/src/${f}")]))
  }
}

# Define o container Python que executará o pipeline
resource "docker_container" "python_app" {
  name  = var.python_container_name   # Nome do container (ex: "case_dados_python")
  image = docker_image.python_app.image_id   # Usa a imagem construída acima

  # Conecta o container à mesma rede 'case_dados' (sem alias, mas pode acessar
  # o PostgreSQL pelo nome "postgres" definido no outro container)
  networks_advanced {
    name = docker_network.case_dados.name
  }

  # Variáveis de ambiente para configurar a conexão com o banco de dados
  # DB_HOST aponta para "postgres" (alias do container PostgreSQL na rede Docker)
  env = [
    "DB_HOST=postgres",
    "DB_PORT=5432",
    "DB_USER=${var.db_admin_user}",
    "DB_PASSWORD=${var.db_admin_password}",
    "DB_NAME=${var.db_name}",
  ]

  # Monta o diretório 'data' do projeto na máquina host dentro do container em '/app/data'
  # Assim os arquivos gerados (raw, trusted, delivery) ficam acessíveis fora do container.
  volumes {
    host_path      = abspath("${var.project_path}/data")
    container_path = "/app/data"
  }

  # Define o comando de entrada do container:
  # - Se var.run_pipeline_on_apply for true, executa 'python3 run_all.py' (pipeline completo)
  # - Caso contrário, mantém o container em execução com 'sleep infinity'
  #   para permitir execução manual (ex: docker exec ... run_all.py)
  command = var.run_pipeline_on_apply ? ["python3", "run_all.py"] : ["sleep", "infinity"]

  # Depende do banco de dados já criado (postgresql_database.case_dados)
  depends_on = [postgresql_database.case_dados]

  # must_run = false porque o pipeline (run_all.py) termina sozinho (exit 0)
  # Se must_run = true, o Terraform tentaria recriar o container a cada apply.
  must_run = false
  attach   = false   # Não anexa a saída do container ao terminal (execução em background)
  logs     = true    # Permite capturar logs do container
}
