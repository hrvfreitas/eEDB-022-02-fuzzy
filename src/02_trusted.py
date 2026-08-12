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
import os                     # Para manipular caminhos e diretórios
import re                     # Para operações com expressões regulares

import pandas as pd           # Para manipulação de dados tabulares

from db import get_engine     # Importa função que cria conexão com PostgreSQL
from fuzzy_match import normalizar_nome, resolver_pendentes_por_fuzzy   # Funções auxiliares para correspondência aproximada

# Score mínimo (0-100) para aceitar uma correspondência fuzzy automaticamente.
# Abaixo disso, a linha fica sem CNPJ (assim como hoje) em vez de arriscar
# um cruzamento errado; os campos *_fuzzy_candidato/*_fuzzy_score registram
# o que foi tentado, para auditoria.
FUZZY_SCORE_MINIMO = 83

# Define o diretório onde serão salvos os arquivos Parquet da camada Trusted
TRUSTED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "trusted")
# Cria o diretório (e subdiretórios) se não existir
os.makedirs(TRUSTED_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# Reclamações
# --------------------------------------------------------------------------- #
def tratar_reclamacoes(df_raw: pd.DataFrame, bancos: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica limpeza e padronização na base de reclamações do BACEN.
    Parâmetros:
        df_raw: DataFrame lido da tabela raw.reclamacoes
        bancos: DataFrame já tratado da base de Bancos (para resolver CNPJ de conglomerados)
    Retorna: DataFrame tratado
    """
    # Cria uma cópia para não modificar o original
    df = df_raw.copy()

    # remove coluna fantasma (gerada pelo ";" final do cabeçalho original)
    # Filtra as colunas que NÃO começam com "Unnamed" (padrão do pandas para colunas sem nome)
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

    # Renomeia as colunas para nomes padronizados (em minúsculo, sem acentos)
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

    # Remove espaços extras no início/fim das colunas de texto
    for col in ["categoria", "tipo", "instituicao_financeira"]:
        df[col] = df[col].str.strip()

    # Converte 'ano' para numérico (inteiro) e depois para Int64 (nullable)
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    # Extrai o número do trimestre (ex: "1º" -> 1) e converte para Int64
    df["trimestre"] = df["trimestre"].str.extract(r"(\d)").astype("Int64")

    # Padroniza CNPJ: remove espaços, substitui vazio por NA, e remove zeros à esquerda (para compatibilidade com outras bases)
    df["cnpj"] = df["cnpj"].str.strip()
    df.loc[df["cnpj"] == "", "cnpj"] = pd.NA
    # Converte para inteiro e depois para string (remove zeros à esquerda) se não for nulo
    df["cnpj"] = df["cnpj"].apply(lambda v: str(int(v)) if pd.notna(v) else v)

    # Trata o índice: troca vírgula por ponto, remove espaços, vira NA se vazio
    df["indice"] = (
        df["indice"].str.strip().str.replace(",", ".", regex=False).replace("", pd.NA)
    )
    # Converte para float (valores inválidos viram NaN)
    df["indice"] = pd.to_numeric(df["indice"], errors="coerce")

    # Lista das colunas que são quantidades (inteiros)
    colunas_qtd = [
        "qtd_reclamacoes_reguladas_procedentes",
        "qtd_reclamacoes_reguladas_outras",
        "qtd_reclamacoes_nao_reguladas",
        "qtd_total_reclamacoes",
        "qtd_total_clientes_ccs_scr",
        "qtd_clientes_ccs",
        "qtd_clientes_scr",
    ]
    # Para cada uma: converte para string, remove espaços, vazio -> NA, e converte para Int64
    for col in colunas_qtd:
        df[col] = df[col].astype(str).str.strip().replace("", pd.NA)
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # Mantém a coluna com o nome do arquivo de origem (já presente no raw)
    df["arquivo_origem"] = df["arquivo_origem"]

    # Remove linhas duplicadas (exatamente iguais)
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

    # Cria um DataFrame auxiliar com todos os nomes (oficial e alternativo) e seus CNPJs
    bancos_nome = bancos[["cnpj", "segmento", "nome_banco", "nome_alternativo"]].copy()
    # Nomes oficiais
    lookup_oficial = bancos_nome[["cnpj", "segmento", "nome_banco"]].rename(columns={"nome_banco": "nome"})
    # Nomes alternativos (quando houver)
    lookup_alt = (
        bancos_nome[bancos_nome["nome_alternativo"].notna()][["cnpj", "segmento", "nome_alternativo"]]
        .rename(columns={"nome_alternativo": "nome"})
    )
    # Concatena os dois
    lookup_nomes = pd.concat([lookup_oficial, lookup_alt], ignore_index=True)
    # Cria uma coluna de junção: remove " - PRUDENCIAL", tira espaços e coloca em maiúsculo
    lookup_nomes["nome_join"] = (
        lookup_nomes["nome"].str.replace(" - PRUDENCIAL", "", regex=False).str.strip().str.upper()
    )
    # Remove duplicatas de nome_join (mantém o primeiro CNPJ encontrado)
    lookup_nomes = lookup_nomes.drop_duplicates(subset="nome_join")[["nome_join", "cnpj", "segmento"]]

    # Identifica linhas que são "Conglomerado"
    mascara_conglomerado = df["tipo"] == "Conglomerado"
    # Cria coluna auxiliar para junção
    df["nome_join"] = pd.NA
    # Para conglomerados, extrai o nome (remove sufixo "(conglomerado)") e padroniza
    df.loc[mascara_conglomerado, "nome_join"] = (
        df.loc[mascara_conglomerado, "instituicao_financeira"]
        .str.replace(r"\s*\(conglomerado\)\s*$", "", regex=True)
        .str.strip()
        .str.upper()
    )

    # Faz o merge (left join) com o lookup para trazer o CNPJ resolvido
    df = df.merge(lookup_nomes, on="nome_join", how="left", suffixes=("", "_resolvido"))

    # ------------------------------------------------------------- #
    # Fallback fuzzy: para conglomerados que NÃO bateram no cruzamento
    # exato acima (sigla, pontuação, acentuação ou ordem de palavras
    # diferente entre "instituicao_financeira" e o nome oficial em
    # Bancos), tenta uma correspondência aproximada antes de considerar
    # o CNPJ como "não encontrado".
    # ------------------------------------------------------------- #
    # Cria colunas com nomes normalizados (para fuzzy)
    lookup_nomes["nome_norm"] = lookup_nomes["nome_join"].apply(normalizar_nome)
    df["nome_norm"] = df["nome_join"].apply(normalizar_nome)
    # Filtra os conglomerados que ainda não têm CNPJ resolvido
    mascara_pendente = mascara_conglomerado & df["cnpj_resolvido"].isna()

    # Aplica a função de resolução fuzzy, que preenche cnpj_resolvido e adiciona colunas auxiliares de score/candidato
    df = resolver_pendentes_por_fuzzy(
        df,
        mascara_pendente=mascara_pendente,
        coluna_nome_origem="nome_norm",
        lookup=lookup_nomes,
        coluna_nome_lookup="nome_norm",
        colunas_retorno={"cnpj": "cnpj_resolvido"},
        score_minimo=FUZZY_SCORE_MINIMO,
    )

    # Preenche o CNPJ original com o resolvido (quando disponível)
    df["cnpj"] = df["cnpj"].fillna(df["cnpj_resolvido"])

    # Cria coluna "cnpj_origem" para documentar como o CNPJ foi obtido
    df["cnpj_origem"] = pd.NA
    df.loc[df["tipo"] == "Banco/financeira", "cnpj_origem"] = "direto (CNPJ na origem)"
    df.loc[mascara_conglomerado & df["cnpj_resolvido"].notna() & df["nome_norm_fuzzy_score"].isna(), "cnpj_origem"] = "resolvido pelo nome do conglomerado (match exato)"
    df.loc[mascara_conglomerado & df["nome_norm_fuzzy_score"].notna(), "cnpj_origem"] = (
        "resolvido pelo nome do conglomerado (fuzzy match, score=" + df["nome_norm_fuzzy_score"].astype("Int64").astype(str) + ")"
    )
    df.loc[mascara_conglomerado & df["cnpj_resolvido"].isna(), "cnpj_origem"] = "nao encontrado (ex.: fintechs/IPs fora do enquadramento de Bancos)"

    # Remove colunas auxiliares que não serão mais necessárias
    df = df.drop(
        columns=["nome_join", "nome_norm", "cnpj_resolvido", "segmento", "nome_norm_fuzzy_candidato", "nome_norm_fuzzy_score"],
        errors="ignore",
    )

    # Define a ordem final das colunas
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
    # Retorna o DataFrame com as colunas finais e índice reiniciado
    return df[colunas_finais].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Bancos (enquadramento / segmento)
# --------------------------------------------------------------------------- #
def tratar_bancos(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica limpeza e padronização na base de enquadramento de bancos.
    Remove duplicatas de CNPJ, mantendo o nome com "- PRUDENCIAL" como oficial.
    """
    # Cria cópia
    df = df_raw.copy()
    # Renomeia colunas para padrão
    df = df.rename(columns={"Segmento": "segmento", "CNPJ": "cnpj", "Nome": "nome"})
    # Remove espaços extras
    df["segmento"] = df["segmento"].str.strip()
    df["cnpj"] = df["cnpj"].str.strip()
    # Padroniza CNPJ removendo zeros à esquerda
    df["cnpj"] = df["cnpj"].apply(lambda v: str(int(v)) if pd.notna(v) and v != "" else v)
    df["nome"] = df["nome"].str.strip()

    # Cria flag indicando se o nome contém "PRUDENCIAL"
    df["eh_nome_prudencial"] = df["nome"].str.contains("PRUDENCIAL", case=False)

    # Para CNPJs duplicados (nome consolidado "- PRUDENCIAL" x razão social
    # da instituição individual), mantém o nome "- PRUDENCIAL" como
    # nome oficial e guarda o outro como nome_alternativo.
    # Ordena para que os nomes com "PRUDENCIAL" fiquem primeiro
    df = df.sort_values(by=["cnpj", "eh_nome_prudencial"], ascending=[True, False])

    # Cria série com os nomes alternativos (os que NÃO são prudenciais), um por CNPJ
    alternativos = (
        df[~df["eh_nome_prudencial"]]
        .drop_duplicates(subset="cnpj")
        .set_index("cnpj")["nome"]
    )

    # Deduplica mantendo o primeiro (que será o prudencial, se existir)
    df_dedup = df.drop_duplicates(subset="cnpj", keep="first").copy()
    # Mapeia o nome alternativo para cada CNPJ
    df_dedup["nome_alternativo"] = df_dedup["cnpj"].map(alternativos)
    # Se o alternativo for igual ao oficial, não é realmente alternativo
    df_dedup.loc[
        df_dedup["nome_alternativo"] == df_dedup["nome"], "nome_alternativo"
    ] = pd.NA

    # Remove colunas auxiliares e renomeia 'nome' para 'nome_banco'
    df_dedup = df_dedup.drop(columns=["eh_nome_prudencial"])
    df_dedup = df_dedup.rename(columns={"nome": "nome_banco"})

    # Retorna com colunas padronizadas
    return df_dedup[
        ["segmento", "cnpj", "nome_banco", "nome_alternativo", "arquivo_origem"]
    ].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Empregados (Glassdoor)
# --------------------------------------------------------------------------- #
# Dicionário de renomeação de colunas (origem -> destino)
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

# Listas de colunas numéricas para conversão
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
    """
    Função auxiliar para converter colunas numéricas do Glassdoor para os tipos corretos.
    """
    for col in COLUNAS_NUMERICAS_INT:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in COLUNAS_NUMERICAS_FLOAT:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["employer_name", "employer_website", "employer_headquarters", "employer_industry", "employer_revenue", "url"]:
        df[col] = df[col].astype(str).str.strip()
    return df


def tratar_empregados(df_match_raw: pd.DataFrame, df_match_less_raw: pd.DataFrame, bancos: pd.DataFrame) -> pd.DataFrame:
    """
    Une as duas fontes de empregados (match e match_less), resolve CNPJ,
    converte tipos e deduplica por CNPJ (priorizando 'match').
    """
    # --- Trata o arquivo match ---
    match = df_match_raw.rename(columns=RENOMEIA_GLASSDOOR).copy()
    # Cria coluna de junção (nome padronizado)
    match["nome_join"] = match["Nome"].str.strip().str.upper()
    match["segmento"] = match["Segmento"].str.strip()
    match["origem_match"] = "match"

    # Tabela de apoio para cruzamento por nome: considera tanto nome oficial quanto alternativo
    bancos_nomes = bancos[["segmento", "cnpj", "nome_banco"]].rename(columns={"nome_banco": "nome"})
    bancos_nomes_alt = (
        bancos[bancos["nome_alternativo"].notna()][["segmento", "cnpj", "nome_alternativo"]]
        .rename(columns={"nome_alternativo": "nome"})
    )
    bancos_join = pd.concat([bancos_nomes, bancos_nomes_alt], ignore_index=True)
    # Padroniza nome de junção (remove " - PRUDENCIAL" e maiúsculo)
    bancos_join["nome_join"] = (
        bancos_join["nome"].str.replace(" - PRUDENCIAL", "", regex=False).str.strip().str.upper()
    )
    # Remove duplicatas por segmento+nome_join
    bancos_join = bancos_join.drop_duplicates(subset=["segmento", "nome_join"])

    # Merge para obter CNPJ (match exato por segmento e nome_join)
    match = match.merge(
        bancos_join[["segmento", "nome_join", "cnpj"]],
        on=["segmento", "nome_join"],
        how="left",
    )

    # ------------------------------------------------------------- #
    # Fallback fuzzy: para nomes que não bateram exatamente
    # ------------------------------------------------------------- #
    # Normaliza os nomes para fuzzy
    match["nome_norm"] = match["nome_join"].apply(normalizar_nome)
    bancos_join["nome_norm"] = bancos_join["nome_join"].apply(normalizar_nome)

    # Para cada segmento onde há CNPJ faltante, tenta fuzzy com os nomes daquele segmento
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

    # Remove coluna auxiliar de normalização
    match = match.drop(columns=["nome_norm"], errors="ignore")

    # --- Trata o arquivo match_less ---
    match_less = df_match_less_raw.rename(columns=RENOMEIA_GLASSDOOR).copy()
    # Já tem CNPJ diretamente
    match_less["cnpj"] = match_less["CNPJ"].str.strip()
    match_less["origem_match"] = "match_less"
    # Acrescenta o segmento via merge com a base de bancos (pelo CNPJ)
    match_less = match_less.merge(
        bancos_join[["cnpj", "segmento"]].drop_duplicates(subset="cnpj"),
        on="cnpj",
        how="left",
    )

    # Lista de colunas comuns para concatenar
    colunas_comuns = list(RENOMEIA_GLASSDOOR.values()) + ["cnpj", "segmento", "origem_match"]

    # Concatena as duas fontes
    empregados = pd.concat(
        [match[colunas_comuns], match_less[colunas_comuns]], ignore_index=True
    )
    # Converte colunas numéricas
    empregados = _tratar_numericos_glassdoor(empregados)
    # Remove duplicatas gerais
    empregados = empregados.drop_duplicates()

    # O arquivo "match_less" contém, em parte, os mesmos empregadores já
    # presentes no arquivo "match" (mesmo CNPJ). Para que o cruzamento com
    # Reclamações não gere duplicidade (fan-out), mantém-se apenas 1 registro
    # por CNPJ: prioriza a origem "match" e, dentro dela, o maior match_percent.
    empregados = empregados[empregados["cnpj"].notna()]
    # Cria coluna de prioridade: match_less = 1 (menor prioridade), match = 0 (maior)
    empregados["prioridade_origem"] = (empregados["origem_match"] == "match_less").astype(int)
    # Ordena: primeiro CNPJ, depois prioridade (menor = melhor), depois match_percent decrescente
    empregados = empregados.sort_values(
        by=["cnpj", "prioridade_origem", "match_percent"], ascending=[True, True, False]
    )
    # Mantém apenas o primeiro de cada CNPJ
    empregados = empregados.drop_duplicates(subset="cnpj", keep="first")
    # Remove coluna auxiliar
    empregados = empregados.drop(columns=["prioridade_origem"])

    return empregados.reset_index(drop=True)


# --------------------------------------------------------------------------- #
def main():
    """
    Função principal: lê os dados da camada RAW, aplica os tratamentos
    e carrega os resultados na camada Trusted (Parquet + PostgreSQL).
    """
    # Obtém a conexão com o banco
    engine = get_engine()

    # Lê as tabelas da camada RAW (schema raw)
    print("Lendo camada RAW do banco relacional...")
    reclamacoes_raw = pd.read_sql_table("reclamacoes", engine, schema="raw")
    bancos_raw = pd.read_sql_table("bancos_enquadramento", engine, schema="raw")
    empregados_match_raw = pd.read_sql_table("empregados_glassdoor_match", engine, schema="raw")
    empregados_match_less_raw = pd.read_sql_table("empregados_glassdoor_match_less", engine, schema="raw")

    # Trata a base de Bancos (necessário para resolver CNPJ dos outros)
    print("Tratando Bancos (enquadramento)...")
    bancos = tratar_bancos(bancos_raw)
    print(f"  -> {len(bancos)} linhas tratadas (deduplicadas por CNPJ)")

    # Trata Reclamações
    print("Tratando Reclamações...")
    reclamacoes = tratar_reclamacoes(reclamacoes_raw, bancos)
    print(f"  -> {len(reclamacoes)} linhas tratadas")
    print(f"  -> CNPJ resolvido para {reclamacoes['cnpj'].notna().sum()} de {len(reclamacoes)} linhas")
    print("  -> " + reclamacoes["cnpj_origem"].value_counts(dropna=False).to_string().replace("\n", "\n     "))

    # Trata Empregados
    print("Tratando Empregados (Glassdoor)...")
    empregados = tratar_empregados(empregados_match_raw, empregados_match_less_raw, bancos)
    print(f"  -> {len(empregados)} linhas tratadas")
    print(f"  -> CNPJ resolvido para {empregados['cnpj'].notna().sum()} de {len(empregados)} empregadores")

    # Salva os DataFrames tratados em arquivos Parquet (camada Trusted em disco)
    print("\nSalvando camada Trusted em Parquet (data/trusted/)...")
    reclamacoes.to_parquet(os.path.join(TRUSTED_DIR, "reclamacoes.parquet"), index=False)
    bancos.to_parquet(os.path.join(TRUSTED_DIR, "bancos.parquet"), index=False)
    empregados.to_parquet(os.path.join(TRUSTED_DIR, "empregados_glassdoor.parquet"), index=False)

    # Carrega os DataFrames tratados no banco PostgreSQL, schema "trusted"
    print("Carregando camada Trusted no banco relacional (schema 'trusted')...")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS trusted;")   # Cria o schema se não existir

    # Substitui as tabelas (if_exists='replace') com os dados tratados
    reclamacoes.to_sql("reclamacoes", engine, schema="trusted", if_exists="replace", index=False)
    bancos.to_sql("bancos", engine, schema="trusted", if_exists="replace", index=False)
    empregados.to_sql("empregados_glassdoor", engine, schema="trusted", if_exists="replace", index=False)

    print("Camada Trusted concluída com sucesso.")


# Se o script for executado diretamente, chama a função main
if __name__ == "__main__":
    main()
```
