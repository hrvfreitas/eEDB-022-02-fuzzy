# --- Postgres ---

output "db_host" {
  description = "Host do PostgreSQL a partir da máquina host (use este valor em src/db.py -> DB_HOST se rodar o pipeline fora do Docker)."
  value       = "localhost"
}

output "db_port" {
  description = "Porta do PostgreSQL publicada em localhost."
  value       = var.db_port
}

output "db_name" {
  description = "Nome do database criado."
  value       = postgresql_database.case_dados.name
}

output "db_user" {
  description = "Usuário do PostgreSQL."
  value       = var.db_admin_user
}

output "connection_string" {
  description = "String de conexão (via localhost) equivalente à CONN_STRING de src/db.py."
  value       = "postgresql+psycopg2://${var.db_admin_user}:${var.db_admin_password}@localhost:${var.db_port}/${postgresql_database.case_dados.name}"
  sensitive   = true
}

# --- Python (pipeline) ---

output "python_container_name" {
  description = "Nome do container que executa o pipeline. Use para ver logs ou rodar novamente."
  value       = docker_container.python_app.name
}

output "ver_logs_do_pipeline" {
  description = "Comando para acompanhar/ver a saída do pipeline."
  value       = "docker logs -f ${docker_container.python_app.name}"
}

output "rodar_pipeline_novamente" {
  description = "Comando para rodar o pipeline de novo sem precisar de 'terraform apply'."
  value       = "docker start -a ${docker_container.python_app.name}"
}
