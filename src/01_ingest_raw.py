"""
ETAPA 1 - INGESTÃO (CAMADA RAW)
================================
Lê todos os arquivos-fonte (Reclamações, Bancos, Empregados) 
  1) Mantém uma cópia em disco da camada RAW (formato livre = arquivos originais),
     em data/raw/origem/ (já copiados).
  2) Ingere TODAS as bases no banco de dados relacional (PostgreSQL), no
     schema "raw", como tabelas espelho das fontes (todas as colunas como
     texto, sem nenhum tratamento/limpeza.

Nenhum tratamento de dado é feito aqui, apenas leitura + carga bruta.
"""
import glob      # Para listar arquivos usando padrões (wildcards)
import os        # Para manipular caminhos e nomes de arquivos

import pandas as pd   # Para leitura e manipulação de dados tabulares

from db import get_engine   # Importa a função que cria a conexão com o PostgreSQL

# Define o diretório onde estão os arquivos originais (camada RAW em disco)
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "origem")


def ler_reclamacoes_raw() -> pd.DataFrame:
    """
    Lê os 8 arquivos trimestrais de reclamações (2021-2022), como texto puro.
    Retorna um único DataFrame com todos os registros.
    """
    # Lista todos os arquivos .csv dentro da pasta "Reclamacoes", ordenados alfabeticamente
    arquivos = sorted(glob.glob(os.path.join(RAW_DIR, "Reclamacoes", "*.csv")))
    dfs = []   # Lista para armazenar os DataFrames de cada arquivo
    for arq in arquivos:   # Itera sobre cada arquivo encontrado
        # Verifica se o arquivo está vazio (tamanho zero)
        if os.path.getsize(arq) == 0:
            # Exemplo: 2022_tri_02_nao_ha_dados.csv -> trimestre sem divulgação, não há o que ingerir
            continue   # Pula este arquivo
        # Lê o CSV com separador ';', codificação 'latin1', todas as colunas como string,
        # e mantém valores vazios como string vazia (não converte para NaN)
        df = pd.read_csv(
            arq,
            sep=";",
            encoding="latin1",
            dtype=str,
            keep_default_na=False,
        )
        # Adiciona uma coluna com o nome do arquivo de origem para rastreabilidade
        df["arquivo_origem"] = os.path.basename(arq)
        dfs.append(df)   # Guarda o DataFrame na lista
    # Concatena todos os DataFrames em um único, ignorando índices
    return pd.concat(dfs, ignore_index=True)


def ler_bancos_raw() -> pd.DataFrame:
    """
    Lê a tabela de enquadramento (segmento) dos bancos, como texto puro.
    Retorna um DataFrame.
    """
    # Define o caminho completo do arquivo TSV
    arq = os.path.join(RAW_DIR, "Bancos", "EnquadramentoInicia_v2.tsv")
    # Lê o TSV com separador tab, codificação 'latin1', tudo como string
    df = pd.read_csv(arq, sep="\t", encoding="latin1", dtype=str, keep_default_na=False)
    # Adiciona coluna com o nome do arquivo de origem
    df["arquivo_origem"] = os.path.basename(arq)
    return df


def ler_empregados_raw(nome_arquivo: str) -> pd.DataFrame:
    """
    Lê um dos arquivos de avaliação Glassdoor, como texto puro.
    Parâmetro: nome_arquivo - nome do arquivo dentro da pasta "Empregados"
    Retorna um DataFrame.
    """
    # Monta o caminho completo do arquivo
    arq = os.path.join(RAW_DIR, "Empregados", nome_arquivo)
    # Lê o CSV com separador '|', codificação UTF-8, tudo como string
    df = pd.read_csv(arq, sep="|", encoding="utf-8", dtype=str, keep_default_na=False)
    # Adiciona coluna com o nome do arquivo de origem
    df["arquivo_origem"] = nome_arquivo
    return df


def carregar_raw_no_banco(engine):
    """
    Função principal que orquestra a leitura de todas as fontes e carrega
    as tabelas no schema 'raw' do PostgreSQL.
    """
    # ----- Leitura das Reclamações -----
    print("Lendo Reclamações (8 arquivos trimestrais)...")
    reclamacoes = ler_reclamacoes_raw()
    print(f"  -> {len(reclamacoes)} linhas")

    # ----- Leitura dos Bancos (enquadramento) -----
    print("Lendo Bancos (enquadramento/segmento)...")
    bancos = ler_bancos_raw()
    print(f"  -> {len(bancos)} linhas")

    # ----- Leitura do arquivo Empregados (match) -----
    print("Lendo Empregados (Glassdoor - match)...")
    empregados_match = ler_empregados_raw("glassdoor_consolidado_join_match_v2.csv")
    print(f"  -> {len(empregados_match)} linhas")

    # ----- Leitura do arquivo Empregados (match_less) -----
    print("Lendo Empregados (Glassdoor - match_less)...")
    empregados_match_less = ler_empregados_raw("glassdoor_consolidado_join_match_less_v2.csv")
    print(f"  -> {len(empregados_match_less)} linhas")

    # ----- Criação do schema raw (se não existir) -----
    print("\nCriando schema 'raw' e carregando tabelas no PostgreSQL...")
    with engine.begin() as conn:   # Inicia uma transação
        # Executa comando SQL para criar o schema, se já existe não faz nada
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS raw;")

    # ----- Carga das tabelas (substitui se já existirem) -----
    # Tabela de reclamações
    reclamacoes.to_sql("reclamacoes", engine, schema="raw", if_exists="replace", index=False)
    # Tabela de enquadramento dos bancos
    bancos.to_sql("bancos_enquadramento", engine, schema="raw", if_exists="replace", index=False)
    # Tabela de empregados (match)
    empregados_match.to_sql("empregados_glassdoor_match", engine, schema="raw", if_exists="replace", index=False)
    # Tabela de empregados (match_less)
    empregados_match_less.to_sql(
        "empregados_glassdoor_match_less", engine, schema="raw", if_exists="replace", index=False
    )
    print("Camada RAW carregada com sucesso no banco (schema 'raw').")


# Se este script for executado diretamente (não importado como módulo)
if __name__ == "__main__":
    # Obtém a engine de conexão com o banco de dados (definida em db.py)
    engine = get_engine()
    # Chama a função principal para realizar a carga
    carregar_raw_no_banco(engine)
