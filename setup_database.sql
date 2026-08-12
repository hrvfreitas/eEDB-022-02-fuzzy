-- Setup inicial do banco de dados relacional (PostgreSQL) usado no projeto.
-- Execute uma única vez, como usuário com permissão de criação de bancos.
--
-- Exemplo (Linux, usuário "postgres" do PostgreSQL):
--   sudo -u postgres psql -f setup_database.sql

CREATE DATABASE case_dados;

-- Os schemas (raw, trusted, delivery) são criados automaticamente pelos
-- scripts Python do pipeline (01_ingest_raw.py, 02_trusted.py, 03_delivery.py).
