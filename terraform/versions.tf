terraform {
  required_version = ">= 1.5"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
    postgresql = {
      source  = "cyrilgdn/postgresql"
      version = "~> 1.21"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
    }
  }
}

provider "docker" {}

# Conecta como superuser (postgres/postgres) dentro do container que este
# mesmo Terraform sobe logo abaixo, para poder criar o database "case_dados"
# (equivalente ao setup_database.sql do projeto).
provider "postgresql" {
  host            = "127.0.0.1"
  port            = var.db_port
  username        = var.db_admin_user
  password        = var.db_admin_password
  sslmode         = "disable"
  connect_timeout = 15
  superuser       = false
}
