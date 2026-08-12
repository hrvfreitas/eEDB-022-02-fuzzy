# Terraform — infraestrutura em Docker (Postgres + Python)

Este diretório provisiona, via Terraform, tudo que o README principal do
projeto pedia para ser feito manualmente:

```bash
# antes:
service postgresql start
psql -U postgres -f setup_database.sql
cd src && python3 run_all.py
```

Em vez disso, o Terraform sobe **dois containers Docker**, na mesma rede:

1. **`postgres`** — imagem `postgres:16-alpine`, expõe a porta `5432` em
   `localhost` e persiste os dados num volume Docker. O Terraform também
   cria o database `case_dados` (equivalente ao `CREATE DATABASE case_dados;`
   do `setup_database.sql`).
2. **`python`** — imagem construída a partir do `Dockerfile` na raiz do
   projeto (Python 3.11 + `requirements.txt` + `src/`). Ao subir, executa
   automaticamente `run_all.py`, que roda o pipeline completo
   (`01_ingest_raw.py` → `02_trusted.py` → `03_delivery.py`), conectando no
   Postgres pelo nome do serviço na rede Docker (`DB_HOST=postgres`).

Os schemas `raw`, `trusted` e `delivery` continuam sendo criados
automaticamente pelos scripts Python — isso não muda. A pasta `data/` do
projeto é montada como volume no container Python, então `data/raw/origem`
(entrada) precisa existir na máquina host antes do apply, e
`data/trusted`/`data/delivery` (saída) aparecem lá depois do pipeline
rodar — sem precisar copiar nada para dentro da imagem.

## Pré-requisitos

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
- [Docker](https://docs.docker.com/get-docker/) instalado e rodando
- Os arquivos de origem já copiados em `data/raw/origem/` (Reclamações,
  Bancos, Empregados), como descrito no README principal

## Como usar

```bash
cd terraform
terraform init
terraform apply
```

Isso builda a imagem Python, sobe o Postgres, cria o database e roda o
pipeline uma vez. Para acompanhar a execução:

```bash
terraform output ver_logs_do_pipeline   # mostra o comando
docker logs -f case_dados_python
```

## Rodar o pipeline de novo (sem `terraform apply`)

O container Python é uma tarefa que termina sozinha (não fica em loop).
Para rodar de novo sem reprovisionar tudo:

```bash
docker start -a case_dados_python
```

Se o código-fonte (`src/`, `requirements.txt` ou `Dockerfile`) mudar, um
novo `terraform apply` detecta a mudança (via `triggers` no
`docker_image.python_app`), reconstrói a imagem e cria um novo container.

## Destruir a infraestrutura

```bash
terraform destroy
```

Isso remove os dois containers, a rede e o volume de dados do PostgreSQL.

## Personalização

Copie `terraform.tfvars.example` para `terraform.tfvars` para sobrescrever
usuário, senha, nome do banco, porta, nomes de imagem/container, etc.

- `run_pipeline_on_apply = false` faz o container Python subir parado
  (`sleep infinity`) em vez de rodar o pipeline sozinho — útil para entrar
  nele manualmente:
  ```bash
  docker exec -it case_dados_python python3 run_all.py
  ```
