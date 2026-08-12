# --- Postgres ---------------------------------------------------------

variable "db_admin_user" {
  description = "Usuário administrador do PostgreSQL (superuser do container)."
  type        = string
  default     = "postgres"
}

variable "db_admin_password" {
  description = "Senha do usuário administrador do PostgreSQL."
  type        = string
  default     = "postgres"
  sensitive   = true
}

variable "db_name" {
  description = "Nome do banco de dados do projeto (mesmo valor usado em src/db.py)."
  type        = string
  default     = "case_dados"
}

variable "db_port" {
  description = "Porta local exposta pelo container do PostgreSQL (mesma usada em src/db.py)."
  type        = number
  default     = 5432
}

variable "postgres_image" {
  description = "Imagem Docker do PostgreSQL a ser utilizada."
  type        = string
  default     = "postgres:16-alpine"
}

variable "postgres_container_name" {
  description = "Nome do container Docker do PostgreSQL."
  type        = string
  default     = "case_dados_postgres"
}

variable "data_volume_name" {
  description = "Nome do volume Docker usado para persistir os dados do PostgreSQL."
  type        = string
  default     = "case_dados_pgdata"
}

# --- Python (pipeline) -------------------------------------------------

variable "project_path" {
  description = "Caminho absoluto (ou relativo a este diretório terraform/) para a raiz do projeto, onde ficam o Dockerfile, src/ e data/."
  type        = string
  default     = ".."
}

variable "python_image_name" {
  description = "Nome/tag da imagem Docker construída a partir do Dockerfile do projeto (pipeline Python)."
  type        = string
  default     = "case_dados_pipeline:latest"
}

variable "python_container_name" {
  description = "Nome do container Docker que executa o pipeline Python (run_all.py)."
  type        = string
  default     = "case_dados_python"
}

variable "network_name" {
  description = "Nome da rede Docker compartilhada pelos containers postgres e python."
  type        = string
  default     = "case_dados_network"
}

variable "run_pipeline_on_apply" {
  description = "Se true, o container Python roda automaticamente (run_all.py) a cada 'terraform apply'. Se false, o container fica parado, pronto para ser iniciado manualmente (ex.: docker start -ai case_dados_python)."
  type        = bool
  default     = true
}
