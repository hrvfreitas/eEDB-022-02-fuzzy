# Case de Engenharia de Dados — Reclamações BACEN + Bancos + Glassdoor

Pipeline de ingestão e tratamento de dados em **Python** (pandas), com carga
em um **banco de dados relacional open source (PostgreSQL)**, organizado em
três camadas de processamento: **RAW → Trusted → Delivery**.

## Bases de origem (pasta `Dados.zip`)

| Base | Arquivo(s) | Conteúdo |
|---|---|---|
| Reclamações | `Reclamações/*.csv` (8 arquivos trimestrais, 2021-2022) | Ranking de reclamações contra instituições financeiras, divulgado pelo Banco Central |
| Bancos | `Bancos/EnquadramentoInicia_v2.tsv` | Enquadramento (segmento prudencial S1-S5) de cada instituição, por CNPJ |
| Empregados | `Empregados/glassdoor_consolidado_join_match_v2.csv` e `..._match_less_v2.csv` | Avaliações de funcionários (Glassdoor) das instituições |

> Observação: o arquivo `2022_tri_02_nao_ha_dados.csv` está vazio — o Banco
> Central não divulgou ranking nesse trimestre — e é ignorado na ingestão.

## Arquitetura das camadas

```
data/raw/origem/        <- arquivos originais, sem nenhuma alteração (evidência da fonte)
     |
     v  (Python / pandas — leitura com encoding/delimitador corretos)
schema "raw" (Postgres)  <- espelho das fontes, todas as colunas como texto, sem tratamento
     |
     v  (Python / pandas — limpeza, tipagem, join de chaves, deduplicação)
data/trusted/*.parquet   <- 3 tabelas tratadas (uma por base), em Parquet
schema "trusted" (Postgres)  <- mesmas 3 tabelas tratadas, também no banco
     |
     v  (Python / pandas — merge das 3 bases pela chave CNPJ)
data/delivery/*.parquet  <- tabela final, tratada e unida, em Parquet
schema "delivery" (Postgres) <- tabela final: delivery.tb_reclamacoes_bancos_funcionarios
```

Todo o **tratamento de dados é feito em Python/pandas** — nenhuma etapa de
limpeza, tipagem, join ou deduplicação usa SQL. O SQL é usado apenas para
criar os schemas (`CREATE SCHEMA`) e o pandas (`to_sql`/`read_sql_table`)
cuida da carga/leitura das tabelas.

## Como rodar

### Opção A — Terraform + Docker (recomendado)

Sobe dois containers (Postgres e Python) e roda o pipeline completo
automaticamente. Requer apenas Docker e Terraform instalados — não precisa
instalar Python/pandas na máquina host.

```bash
cd terraform
terraform init
terraform apply
```

Detalhes, variáveis e como rodar o pipeline de novo:
[`terraform/README.md`](terraform/README.md).

### Opção B — manual (Python local + Postgres local)

```bash
# 1) instalar dependências Python
pip install -r requirements.txt

# 2) subir o PostgreSQL e criar o banco (uma vez só)
service postgresql start
psql -U postgres -f setup_database.sql
# ajuste usuário/senha/host/porta em src/db.py (ou via variáveis de
# ambiente DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME) se necessário

# 3) rodar o pipeline completo
cd src
python3 run_all.py
```

Isso é equivalente a rodar, em sequência:
`01_ingest_raw.py` → `02_trusted.py` → `03_delivery.py`.

## Principais decisões de tratamento

1. **Encoding dos nomes de arquivo**: o zip original trazia o nome da pasta
   "Reclamações" corrompido (bytes em CP850 interpretados incorretamente).
   Corrigido na extração.
2. **Encoding e delimitador de cada fonte**: Reclamações usa `;` e Latin-1;
   Bancos usa `\t` (TSV) e Latin-1; Empregados usa `|` e UTF-8.
3. **Chave de integração = CNPJ (raiz, 8 dígitos)**. A base de Reclamações
   guarda o CNPJ com zeros à esquerda (ex.: `03532415`), enquanto Bancos e
   Empregados não usam zero-padding (ex.: `3532415`). Normalizado para o
   mesmo formato antes do cruzamento.
4. **CNPJ dos grandes bancos ("Conglomerado")**: nas Reclamações, os maiores
   bancos (Bradesco, Itaú, Santander, Banco do Brasil, Caixa, BTG etc.) são
   informados de forma agregada, sem CNPJ (ex.: `"BRADESCO (conglomerado)"`).
   O CNPJ desses registros é **resolvido pelo nome**, casando com o nome
   oficial da instituição na base de Bancos tratada — sem essa etapa, os
   bancos mais relevantes ficariam de fora do cruzamento final. Fintechs e
   instituições de pagamento que não constam na base de enquadramento de
   Bancos (ex.: Nubank, Stone, Inter, C6 Bank) permanecem sem CNPJ resolvido
   e por isso não entram na tabela Delivery — mas continuam disponíveis,
   intactas, na camada Trusted.
5. **Deduplicação de Bancos por CNPJ**: a base de enquadramento trazia, para
   15 CNPJs, duas linhas (o nome consolidado "- PRUDENCIAL" e a razão social
   da instituição individual). Mantido o nome "- PRUDENCIAL" como nome
   oficial, preservando o outro em `nome_alternativo`.
6. **Empregados (Glassdoor)**: os dois arquivos de origem (`match` e
   `match_less`) foram unificados; o CNPJ de cada empregador é obtido direto
   (arquivo `match_less`) ou por cruzamento Segmento+Nome com a base de
   Bancos (arquivo `match`). Registros duplicados entre os dois arquivos
   (mesmo CNPJ) foram consolidados em 1 linha por CNPJ, priorizando o
   registro do arquivo `match`.
7. **Fallback de fuzzy matching para nomes divergentes** (itens 4 e 6):
   quando o cruzamento exato por nome não encontra correspondência (sigla,
   pontuação, acento ou ordem de palavras diferente — ex.: "BCO DO BRASIL
   SA" vs "Banco do Brasil S.A."), uma segunda tentativa usa correspondência
   aproximada (`src/fuzzy_match.py`, RapidFuzz) sobre nomes normalizados.
   Só aceita o match automaticamente com score ≥ 88 (0-100); casos
   resolvidos assim ficam marcados em `cnpj_origem` como "fuzzy match,
   score=N" (em vez de "match exato"), para permitir auditoria.

## Tabela final (Delivery)

`delivery.tb_reclamacoes_bancos_funcionarios` — granularidade **banco x
trimestre**: 703 linhas, 40 colunas, reunindo:
- indicadores de reclamações (índice, quantidades por categoria) — BACEN
- segmento prudencial e nome oficial do banco — enquadramento
- avaliações de funcionários (notas, % recomendação, etc.) — Glassdoor,
  quando disponível (`possui_avaliacao_glassdoor`)

## Estrutura de arquivos

```
Dockerfile               imagem do container Python (pipeline)
.dockerignore
requirements.txt
setup_database.sql
data/
  raw/origem/            arquivos originais (camada RAW em disco)
  trusted/*.parquet      camada Trusted (Parquet)
  delivery/*.parquet     camada Delivery (Parquet)
src/
  db.py                  conexão com o PostgreSQL (lê DB_HOST/DB_PORT/... do ambiente)
  01_ingest_raw.py        ingestão da camada RAW
  02_trusted.py           tratamento -> camada Trusted
  03_delivery.py          união -> camada Delivery (tabela final)
  fuzzy_match.py          fuzzy matching de nomes (RapidFuzz)
  run_all.py              aguarda o Postgres e executa as 3 etapas em sequência
terraform/
  main.tf                 rede Docker + container "postgres" + container "python"
  variables.tf, outputs.tf, versions.tf
  README.md               instruções detalhadas do Terraform
```
