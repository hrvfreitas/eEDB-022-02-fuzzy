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

# --- Rede compartilhada pelos dois containers ---------------------------

resource "docker_network" "case_dados" {
  name = var.network_name
}

# --- Container 1: PostgreSQL --------------------------------------------

resource "docker_image" "postgres" {
  name         = var.postgres_image
  keep_locally = true
}

resource "docker_volume" "pgdata" {
  name = var.data_volume_name
}

resource "docker_container" "postgres" {
  name  = var.postgres_container_name
  image = docker_image.postgres.image_id

  networks_advanced {
    name    = docker_network.case_dados.name
    aliases = ["postgres"] # é assim que o container "python" enxerga o banco (DB_HOST=postgres)
  }

  env = [
    "POSTGRES_USER=${var.db_admin_user}",
    "POSTGRES_PASSWORD=${var.db_admin_password}",
  ]

  # Publicada em localhost também, para facilitar inspeção manual
  # (psql, DBeaver etc.) e para o provider "postgresql" abaixo.
  ports {
    internal = 5432
    external = var.db_port
  }

  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }

  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U ${var.db_admin_user}"]
    interval = "5s"
    timeout  = "3s"
    retries  = 10
  }

  wait     = true
  must_run = true
}

# Aguarda o container ficar pronto antes de tentar conectar via provider postgresql.
resource "time_sleep" "wait_for_postgres" {
  depends_on      = [docker_container.postgres]
  create_duration = "8s"
}

resource "postgresql_database" "case_dados" {
  name  = var.db_name
  owner = var.db_admin_user

  depends_on = [time_sleep.wait_for_postgres]
}

# --- Container 2: Python (pipeline) --------------------------------------

resource "docker_image" "python_app" {
  name = var.python_image_name

  build {
    context  = var.project_path
    dockerfile = "Dockerfile"
  }

  # Reconstrói a imagem sempre que o código-fonte mudar.
  triggers = {
    dockerfile_sha1     = filesha1("${var.project_path}/Dockerfile")
    requirements_sha1   = filesha1("${var.project_path}/requirements.txt")
    src_dir_sha1        = sha1(join("", [for f in fileset("${var.project_path}/src", "**") : filesha1("${var.project_path}/src/${f}")]))
  }
}

resource "docker_container" "python_app" {
  name  = var.python_container_name
  image = docker_image.python_app.image_id

  networks_advanced {
    name = docker_network.case_dados.name
  }

  env = [
    "DB_HOST=postgres", # nome do container/rede Docker, não localhost
    "DB_PORT=5432",
    "DB_USER=${var.db_admin_user}",
    "DB_PASSWORD=${var.db_admin_password}",
    "DB_NAME=${var.db_name}",
  ]

  # data/raw (entrada) e data/trusted, data/delivery (saída) ficam
  # visíveis na máquina host, sem precisar reconstruir a imagem.
  volumes {
    host_path      = abspath("${var.project_path}/data")
    container_path = "/app/data"
  }

  # Se run_pipeline_on_apply = false, o container só fica de pé (sleep
  # infinity) para permitir rodar o pipeline manualmente, ex.:
  #   docker exec -it case_dados_python python3 run_all.py
  command = var.run_pipeline_on_apply ? ["python3", "run_all.py"] : ["sleep", "infinity"]

  depends_on = [postgresql_database.case_dados]

  # must_run = false porque o pipeline (run_all.py) é uma tarefa que
  # termina sozinha (exit 0) quando concluída -- diferente do container
  # "postgres", que é um serviço de longa duração. Com must_run = true o
  # Terraform tentaria recriar o container a cada apply após ele terminar.
  must_run = false
  attach   = false
  logs     = true
}
