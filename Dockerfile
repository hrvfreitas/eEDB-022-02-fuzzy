# Imagem do container "python" do projeto: executa o pipeline
# RAW -> Trusted -> Delivery (01_ingest_raw.py -> 02_trusted.py -> 03_delivery.py).
#
# Os dados (data/raw, data/trusted, data/delivery) NÃO são copiados para a
# imagem: são montados como volume pelo Terraform (docker_container.volumes),
# para que os arquivos de entrada/saída fiquem sempre visíveis na máquina
# host e a imagem não precise ser reconstruída a cada mudança de dado.

FROM python:3.11-slim

WORKDIR /app

# Dependências primeiro, para aproveitar o cache de camadas do Docker.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código-fonte do pipeline.
COPY src/ ./src

WORKDIR /app/src

# Espera o Postgres ficar pronto (db.wait_for_db) e roda as 3 etapas em sequência.
CMD ["python3", "run_all.py"]
