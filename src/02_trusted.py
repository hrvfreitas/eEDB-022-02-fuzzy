"""
ETAPA 2 - TRATAMENTO (CAMADA TRUSTED)
=======================================
Lê os dados brutos da camada RAW (banco de dados, schema "raw") e aplica,
usando exclusivamente Python/pandas, a limpeza e
padronização de cada base:

  * Reclamações (BACEN):
      - Corrige encoding e nomes de coluna
      - "Trimestre" (ex.: "1º") -> inteiro (1..4)
      - "Índice" (ex.: "54,79") -> float (54.79), vazio -> NaN
      - Quantidades -> inteiro, vazio -> NaN
      - CNPJ -> string padronizada (sem espaços), vazio -> NaN
      - Remove coluna fantasma gerada pelo ";" final do cabeçalho de origem
      - Resolve o CNPJ das linhas "Conglomerado" (grandes bancos, ex.:
        "BRADESCO (conglomerado)"), que não vêm com CNPJ na origem, casando
        o nome do conglomerado com o nome oficial na base de Bancos já
        tratada

  * Bancos (enquadramento/segmento):
      - Padroniza nomes e remove espaços
      - Remove duplicidade de CNPJ (havia CNPJs com 2 nomes: o nome
        consolidado "- PRUDENCIAL" e a razão social da instituição
        individual) mantendo o nome "- PRUDENCIAL" como nome oficial e
        preservando o outro como "nome_alternativo"

  * Empregados (Glassdoor):
      - Une os dois arquivos (match e match_less) em uma única base,
        marcando a origem de cada registro
      - Resolve o CNPJ de cada empregador:
          * arquivo "match" traz Segmento+Nome  -> CNPJ é obtido cruzando
            com a base de Bancos tratada
          * arquivo "match_less" já traz o CNPJ diretamente
      - Converte contagens e notas para tipos numéricos

O resultado de cada base tratada é salvo em Parquet (data/trusted/*.parquet)
e carregado no banco relacional, no schema "trusted".
"""
import os
import re

import pandas as pd

from db import get_engine
from fuzzy_match import normalizar_nome, resolver_pendentes_por_fuzzy

# Score mínimo (0-100) para aceitar uma correspondência fuzzy automaticamente.
# Abaixo disso, a linha fica sem CNPJ (assim como hoje) em vez de arriscar
# um cruzamento errado; os campos *_fuzzy_candidato/*_fuzzy_score registram
# o que foi tentado, para auditoria.
FUZZY_SCORE_MINIMO = 83

TRUSTED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "trusted")
os.makedirs(TRUSTED_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# Reclamações
# --------------------------------------------------------------------------- #
def tratar_reclamacoes(df_raw: pd.DataFrame, bancos: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()

    # remove coluna fantasma (";" final do cabeçalho original)
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

    df = df.rename(
        columns={
            "Ano": "ano",
            "Trimestre": "trimestre",
            "Categoria": "categoria",
            "Tipo": "tipo",
            "CNPJ IF": "cnpj",
            "Instituição financeira": "instituicao_financeira",
            "Índice": "indice",
            "Quantidade de reclamações reguladas procedentes": "qtd_reclamacoes_reguladas_procedentes",
            "Quantidade de reclamações reguladas - outras": "qtd_reclamacoes_reguladas_outras",
            "Quantidade de reclamações não reguladas": "qtd_reclamacoes_nao_reguladas",
            "Quantidade total de reclamações": "qtd_total_reclamacoes",
            "Quantidade total de clientes \x96 CCS e SCR": "qtd_total_clientes_ccs_scr",
            "Quantidade de clientes \x96 CCS": "qtd_clientes_ccs",
            "Quantidade de clientes \x96 SCR": "qtd_clientes_scr",
        }
    )

    for col in ["categoria", "tipo", "instituicao_financeira"]:
        df[col] = df[col].str.strip()

    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    df["trimestre"] = df["trimestre"].str.extract(r"(\d)").astype("Int64")

    df["cnpj"] = df["cnpj"].str.strip()
    df.loc[df["cnpj"] == "", "cnpj"] = pd.NA
    # normaliza removendo zeros à esquerda (a base de Bancos/Empregados não
    # usa zero-padding), garantindo a mesma "forma" da chave de cruzamento
    df["cnpj"] = df["cnpj"].apply(lambda v: str(int(v)) if pd.notna(v) else v)

    df["indice"] = (
        df["indice"].str.strip().str.replace(",", ".", regex=False).replace("", pd.NA)
    )
    df["indice"] = pd.to_numeric(df["indice"], errors="coerce")

    colunas_qtd = [
        "qtd_reclamacoes_reguladas_procedentes",
        "qtd_reclamacoes_reguladas_outras",
        "qtd_reclamacoes_nao_reguladas",
        "qtd_total_reclamacoes",
        "qtd_total_clientes_ccs_scr",
        "qtd_clientes_ccs",
        "qtd_clientes_scr",
    ]
    for col in colunas_qtd:
        df[col] = df[col].astype(str).str.strip().replace("", pd.NA)
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    df["arquivo_origem"] = df["arquivo_origem"]

    # remove duplicatas exatas, se houver
    df = df.drop_duplicates()

    # ----------------------------------------------------------------- #
    # Resolução do CNPJ para as linhas "Conglomerado"
    # ----------------------------------------------------------------- #
    # As linhas do tipo "Banco/financeira" já trazem o CNPJ da instituição
    # individual. Já as linhas "Conglomerado" (usadas pelo BACEN para os
    # grandes bancos, ex.: "BRADESCO (conglomerado)") não têm CNPJ na
    # origem -- porém o NOME do conglomerado corresponde ao nome oficial
    # do banco na base de Bancos (após remover o sufixo "(conglomerado)").
    # Usamos esse nome para resolver o CNPJ e permitir que esses grandes
    # bancos (que são justamente os mais relevantes) entrem no cruzamento
    # final com Empregados/Glassdoor.
    bancos_nome = bancos[["cnpj", "segmento", "nome_banco", "nome_alternativo"]].copy()
    lookup_oficial = bancos_nome[["cnpj", "segmento", "nome_banco"]].rename(columns={"nome_banco": "nome"})
    lookup_alt = (
        bancos_nome[bancos_nome["nome_alternativo"].notna()][["cnpj", "segmento", "nome_alternativo"]]
        .rename(columns={"nome_alternativo": "nome"})
    )
    lookup_nomes = pd.concat([lookup_oficial, lookup_alt], ignore_index=True)
    lookup_nomes["nome_join"] = (
        lookup_nomes["nome"].str.replace(" - PRUDENCIAL", "", regex=False).str.strip().str.upper()
    )
    lookup_nomes = lookup_nomes.drop_duplicates(subset="nome_join")[["nome_join", "cnpj", "segmento"]]

    mascara_conglomerado = df["tipo"] == "Conglomerado"
    df["nome_join"] = pd.NA
    df.loc[mascara_conglomerado, "nome_join"] = (
        df.loc[mascara_conglomerado, "instituicao_financeira"]
        .str.replace(r"\s*\(conglomerado\)\s*$", "", regex=True)
        .str.strip()
        .str.upper()
    )

    df = df.merge(lookup_nomes, on="nome_join", how="left", suffixes=("", "_resolvido"))

    # ------------------------------------------------------------- #
    # Fallback fuzzy: para conglomerados que NÃO bateram no cruzamento
    # exato acima (sigla, pontuação, acentuação ou ordem de palavras
    # diferente entre "instituicao_financeira" e o nome oficial em
    # Bancos), tenta uma correspondência aproximada antes de considerar
    # o CNPJ como "não encontrado".
    # ------------------------------------------------------------- #
    lookup_nomes["nome_norm"] = lookup_nomes["nome_join"].apply(normalizar_nome)
    df["nome_norm"] = df["nome_join"].apply(normalizar_nome)
    mascara_pendente = mascara_conglomerado & df["cnpj_resolvido"].isna()

    df = resolver_pendentes_por_fuzzy(
        df,
        mascara_pendente=mascara_pendente,
        coluna_nome_origem="nome_norm",
        lookup=lookup_nomes,
        coluna_nome_lookup="nome_norm",
        colunas_retorno={"cnpj": "cnpj_resolvido"},
        score_minimo=FUZZY_SCORE_MINIMO,
    )

    df["cnpj"] = df["cnpj"].fillna(df["cnpj_resolvido"])

    df["cnpj_origem"] = pd.NA
    df.loc[df["tipo"] == "Banco/financeira", "cnpj_origem"] = "direto (CNPJ na origem)"
    df.loc[mascara_conglomerado & df["cnpj_resolvido"].notna() & df["nome_norm_fuzzy_score"].isna(), "cnpj_origem"] = "resolvido pelo nome do conglomerado (match exato)"
    df.loc[mascara_conglomerado & df["nome_norm_fuzzy_score"].notna(), "cnpj_origem"] = (
        "resolvido pelo nome do conglomerado (fuzzy match, score=" + df["nome_norm_fuzzy_score"].astype("Int64").astype(str) + ")"
    )
    df.loc[mascara_conglomerado & df["cnpj_resolvido"].isna(), "cnpj_origem"] = "nao encontrado (ex.: fintechs/IPs fora do enquadramento de Bancos)"

    df = df.drop(
        columns=["nome_join", "nome_norm", "cnpj_resolvido", "segmento", "nome_norm_fuzzy_candidato", "nome_norm_fuzzy_score"],
        errors="ignore",
    )

    colunas_finais = [
        "ano",
        "trimestre",
        "categoria",
        "tipo",
        "cnpj",
        "cnpj_origem",
        "instituicao_financeira",
        "indice",
        *colunas_qtd,
        "arquivo_origem",
    ]
    return df[colunas_finais].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Bancos (enquadramento / segmento)
# --------------------------------------------------------------------------- #
def tratar_bancos(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()
    df = df.rename(columns={"Segmento": "segmento", "CNPJ": "cnpj", "Nome": "nome"})
    df["segmento"] = df["segmento"].str.strip()
    df["cnpj"] = df["cnpj"].str.strip()
    df["cnpj"] = df["cnpj"].apply(lambda v: str(int(v)) if pd.notna(v) and v != "" else v)
    df["nome"] = df["nome"].str.strip()

    df["eh_nome_prudencial"] = df["nome"].str.contains("PRUDENCIAL", case=False)

    # Para CNPJs duplicados (nome consolidado "- PRUDENCIAL" x razão social
    # da instituição individual), mantém o nome "- PRUDENCIAL" como
    # nome oficial e guarda o outro como nome_alternativo.
    df = df.sort_values(by=["cnpj", "eh_nome_prudencial"], ascending=[True, False])

    alternativos = (
        df[~df["eh_nome_prudencial"]]
        .drop_duplicates(subset="cnpj")
        .set_index("cnpj")["nome"]
    )

    df_dedup = df.drop_duplicates(subset="cnpj", keep="first").copy()
    df_dedup["nome_alternativo"] = df_dedup["cnpj"].map(alternativos)
    # se o nome oficial não continha "PRUDENCIAL" (não havia par), não há alternativo
    df_dedup.loc[
        df_dedup["nome_alternativo"] == df_dedup["nome"], "nome_alternativo"
    ] = pd.NA

    df_dedup = df_dedup.drop(columns=["eh_nome_prudencial"])
    df_dedup = df_dedup.rename(columns={"nome": "nome_banco"})

    return df_dedup[
        ["segmento", "cnpj", "nome_banco", "nome_alternativo", "arquivo_origem"]
    ].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Empregados (Glassdoor)
# --------------------------------------------------------------------------- #
RENOMEIA_GLASSDOOR = {
    "employer_name": "employer_name",
    "reviews_count": "reviews_count",
    "culture_count": "culture_count",
    "salaries_count": "salaries_count",
    "benefits_count": "benefits_count",
    "employer-website": "employer_website",
    "employer-headquarters": "employer_headquarters",
    "employer-founded": "employer_founded",
    "employer-industry": "employer_industry",
    "employer-revenue": "employer_revenue",
    "url": "url",
    "Geral": "nota_geral",
    "Cultura e valores": "nota_cultura_valores",
    "Diversidade e inclusão": "nota_diversidade_inclusao",
    "Qualidade de vida": "nota_qualidade_vida",
    "Alta liderança": "nota_alta_lideranca",
    "Remuneração e benefícios": "nota_remuneracao_beneficios",
    "Oportunidades de carreira": "nota_oportunidades_carreira",
    "Recomendam para outras pessoas(%)": "pct_recomendam_empresa",
    "Perspectiva positiva da empresa(%)": "pct_perspectiva_positiva",
    "match_percent": "match_percent",
}

COLUNAS_NUMERICAS_INT = ["reviews_count", "culture_count", "salaries_count", "benefits_count", "match_percent"]
COLUNAS_NUMERICAS_FLOAT = [
    "employer_founded",
    "nota_geral",
    "nota_cultura_valores",
    "nota_diversidade_inclusao",
    "nota_qualidade_vida",
    "nota_alta_lideranca",
    "nota_remuneracao_beneficios",
    "nota_oportunidades_carreira",
    "pct_recomendam_empresa",
    "pct_perspectiva_positiva",
]


def _tratar_numericos_glassdoor(df: pd.DataFrame) -> pd.DataFrame:
    for col in COLUNAS_NUMERICAS_INT:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in COLUNAS_NUMERICAS_FLOAT:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["employer_name", "employer_website", "employer_headquarters", "employer_industry", "employer_revenue", "url"]:
        df[col] = df[col].astype(str).str.strip()
    return df


def tratar_empregados(df_match_raw: pd.DataFrame, df_match_less_raw: pd.DataFrame, bancos: pd.DataFrame) -> pd.DataFrame:
    match = df_match_raw.rename(columns=RENOMEIA_GLASSDOOR).copy()
    match["nome_join"] = match["Nome"].str.strip().str.upper()
    match["segmento"] = match["Segmento"].str.strip()
    match["origem_match"] = "match"

    # tabela de apoio para o cruzamento por nome: considera tanto o nome
    # oficial ("- PRUDENCIAL") quanto o nome alternativo (razão social),
    # pois o Glassdoor às vezes usa a razão social da instituição
    bancos_nomes = bancos[["segmento", "cnpj", "nome_banco"]].rename(columns={"nome_banco": "nome"})
    bancos_nomes_alt = (
        bancos[bancos["nome_alternativo"].notna()][["segmento", "cnpj", "nome_alternativo"]]
        .rename(columns={"nome_alternativo": "nome"})
    )
    bancos_join = pd.concat([bancos_nomes, bancos_nomes_alt], ignore_index=True)
    bancos_join["nome_join"] = (
        bancos_join["nome"].str.replace(" - PRUDENCIAL", "", regex=False).str.strip().str.upper()
    )
    bancos_join = bancos_join.drop_duplicates(subset=["segmento", "nome_join"])

    match = match.merge(
        bancos_join[["segmento", "nome_join", "cnpj"]],
        on=["segmento", "nome_join"],
        how="left",
    )

    # ------------------------------------------------------------- #
    # Fallback fuzzy: empregadores do Glassdoor cujo nome não bateu
    # exatamente com o nome oficial/alternativo em Bancos (abreviação,
    # pontuação, "S.A." vs "SA", acentuação, etc.). Restrito ao mesmo
    # segmento, para não cruzar por engano com um banco de outro porte.
    # ------------------------------------------------------------- #
    match["nome_norm"] = match["nome_join"].apply(normalizar_nome)
    bancos_join["nome_norm"] = bancos_join["nome_join"].apply(normalizar_nome)

    for segmento_atual in match.loc[match["cnpj"].isna(), "segmento"].dropna().unique():
        mascara_pendente = (match["segmento"] == segmento_atual) & match["cnpj"].isna()
        lookup_segmento = bancos_join[bancos_join["segmento"] == segmento_atual]
        match = resolver_pendentes_por_fuzzy(
            match,
            mascara_pendente=mascara_pendente,
            coluna_nome_origem="nome_norm",
            lookup=lookup_segmento,
            coluna_nome_lookup="nome_norm",
            colunas_retorno={"cnpj": "cnpj"},
            score_minimo=FUZZY_SCORE_MINIMO,
        )

    match = match.drop(columns=["nome_norm"], errors="ignore")

    match_less = df_match_less_raw.rename(columns=RENOMEIA_GLASSDOOR).copy()
    match_less["cnpj"] = match_less["CNPJ"].str.strip()
    match_less["origem_match"] = "match_less"
    match_less = match_less.merge(
        bancos_join[["cnpj", "segmento"]].drop_duplicates(subset="cnpj"),
        on="cnpj",
        how="left",
    )

    colunas_comuns = list(RENOMEIA_GLASSDOOR.values()) + ["cnpj", "segmento", "origem_match"]

    empregados = pd.concat(
        [match[colunas_comuns], match_less[colunas_comuns]], ignore_index=True
    )
    empregados = _tratar_numericos_glassdoor(empregados)
    empregados = empregados.drop_duplicates()

    # O arquivo "match_less" contém, em parte, os mesmos empregadores já
    # presentes no arquivo "match" (mesmo CNPJ). Para que o cruzamento com
    # Reclamações não gere duplicidade (fan-out), mantém-se apenas 1 registro
    # por CNPJ: prioriza a origem "match" e, dentro dela, o maior match_percent.
    empregados = empregados[empregados["cnpj"].notna()]
    empregados["prioridade_origem"] = (empregados["origem_match"] == "match_less").astype(int)
    empregados = empregados.sort_values(
        by=["cnpj", "prioridade_origem", "match_percent"], ascending=[True, True, False]
    )
    empregados = empregados.drop_duplicates(subset="cnpj", keep="first")
    empregados = empregados.drop(columns=["prioridade_origem"])

    return empregados.reset_index(drop=True)


# --------------------------------------------------------------------------- #
def main():
    engine = get_engine()

    print("Lendo camada RAW do banco relacional...")
    reclamacoes_raw = pd.read_sql_table("reclamacoes", engine, schema="raw")
    bancos_raw = pd.read_sql_table("bancos_enquadramento", engine, schema="raw")
    empregados_match_raw = pd.read_sql_table("empregados_glassdoor_match", engine, schema="raw")
    empregados_match_less_raw = pd.read_sql_table("empregados_glassdoor_match_less", engine, schema="raw")

    print("Tratando Bancos (enquadramento)...")
    bancos = tratar_bancos(bancos_raw)
    print(f"  -> {len(bancos)} linhas tratadas (deduplicadas por CNPJ)")

    print("Tratando Reclamações...")
    reclamacoes = tratar_reclamacoes(reclamacoes_raw, bancos)
    print(f"  -> {len(reclamacoes)} linhas tratadas")
    print(f"  -> CNPJ resolvido para {reclamacoes['cnpj'].notna().sum()} de {len(reclamacoes)} linhas")
    print("  -> " + reclamacoes["cnpj_origem"].value_counts(dropna=False).to_string().replace("\n", "\n     "))

    print("Tratando Empregados (Glassdoor)...")
    empregados = tratar_empregados(empregados_match_raw, empregados_match_less_raw, bancos)
    print(f"  -> {len(empregados)} linhas tratadas")
    print(f"  -> CNPJ resolvido para {empregados['cnpj'].notna().sum()} de {len(empregados)} empregadores")

    print("\nSalvando camada Trusted em Parquet (data/trusted/)...")
    reclamacoes.to_parquet(os.path.join(TRUSTED_DIR, "reclamacoes.parquet"), index=False)
    bancos.to_parquet(os.path.join(TRUSTED_DIR, "bancos.parquet"), index=False)
    empregados.to_parquet(os.path.join(TRUSTED_DIR, "empregados_glassdoor.parquet"), index=False)

    print("Carregando camada Trusted no banco relacional (schema 'trusted')...")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS trusted;")

    reclamacoes.to_sql("reclamacoes", engine, schema="trusted", if_exists="replace", index=False)
    bancos.to_sql("bancos", engine, schema="trusted", if_exists="replace", index=False)
    empregados.to_sql("empregados_glassdoor", engine, schema="trusted", if_exists="replace", index=False)

    print("Camada Trusted concluída com sucesso.")


if __name__ == "__main__":
    main()
