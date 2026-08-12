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
import glob
import os

import pandas as pd

from db import get_engine

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "origem")


def ler_reclamacoes_raw() -> pd.DataFrame:
    """Lê os 8 arquivos trimestrais de reclamações (2021-2022), como texto puro."""
    arquivos = sorted(glob.glob(os.path.join(RAW_DIR, "Reclamacoes", "*.csv")))
    dfs = []
    for arq in arquivos:
        if os.path.getsize(arq) == 0:
            # ex: 2022_tri_02_nao_ha_dados.csv -> trimestre sem divulgação, não há o que ingerir
            continue
        df = pd.read_csv(
            arq,
            sep=";",
            encoding="latin1",
            dtype=str,
            keep_default_na=False,
        )
        df["arquivo_origem"] = os.path.basename(arq)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def ler_bancos_raw() -> pd.DataFrame:
    """Lê a tabela de enquadramento (segmento) dos bancos, como texto puro."""
    arq = os.path.join(RAW_DIR, "Bancos", "EnquadramentoInicia_v2.tsv")
    df = pd.read_csv(arq, sep="\t", encoding="latin1", dtype=str, keep_default_na=False)
    df["arquivo_origem"] = os.path.basename(arq)
    return df


def ler_empregados_raw(nome_arquivo: str) -> pd.DataFrame:
    """Lê um dos arquivos de avaliação Glassdoor, como texto puro."""
    arq = os.path.join(RAW_DIR, "Empregados", nome_arquivo)
    df = pd.read_csv(arq, sep="|", encoding="utf-8", dtype=str, keep_default_na=False)
    df["arquivo_origem"] = nome_arquivo
    return df


def carregar_raw_no_banco(engine):
    print("Lendo Reclamações (8 arquivos trimestrais)...")
    reclamacoes = ler_reclamacoes_raw()
    print(f"  -> {len(reclamacoes)} linhas")

    print("Lendo Bancos (enquadramento/segmento)...")
    bancos = ler_bancos_raw()
    print(f"  -> {len(bancos)} linhas")

    print("Lendo Empregados (Glassdoor - match)...")
    empregados_match = ler_empregados_raw("glassdoor_consolidado_join_match_v2.csv")
    print(f"  -> {len(empregados_match)} linhas")

    print("Lendo Empregados (Glassdoor - match_less)...")
    empregados_match_less = ler_empregados_raw("glassdoor_consolidado_join_match_less_v2.csv")
    print(f"  -> {len(empregados_match_less)} linhas")

    print("\nCriando schema 'raw' e carregando tabelas no PostgreSQL...")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS raw;")

    reclamacoes.to_sql("reclamacoes", engine, schema="raw", if_exists="replace", index=False)
    bancos.to_sql("bancos_enquadramento", engine, schema="raw", if_exists="replace", index=False)
    empregados_match.to_sql("empregados_glassdoor_match", engine, schema="raw", if_exists="replace", index=False)
    empregados_match_less.to_sql(
        "empregados_glassdoor_match_less", engine, schema="raw", if_exists="replace", index=False
    )
    print("Camada RAW carregada com sucesso no banco (schema 'raw').")


if __name__ == "__main__":
    engine = get_engine()
    carregar_raw_no_banco(engine)
