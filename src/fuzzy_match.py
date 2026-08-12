"""
FUZZY MATCHING DE NOMES (fallback para o cruzamento por nome)
================================================================
Usado como segunda tentativa quando o cruzamento exato por nome
normalizado (upper + strip) não encontra correspondência -- por
exemplo, nomes com sigla/abreviação diferente, pontuação (S.A., LTDA),
acentuação ou ordem de palavras diferente entre as bases (Reclamações
BACEN, Bancos/enquadramento e Empregados/Glassdoor).

Motor usado: RapidFuzz (rapidfuzz.process + fuzz.token_sort_ratio),
que tolera palavras fora de ordem (ex.: "UNIBANCO ITAU" casa com
"ITAU UNIBANCO").
"""
import re
import unicodedata

import pandas as pd
from rapidfuzz import fuzz, process

# Sufixos/termos societários que atrapalham a comparação e não ajudam a
# distinguir uma instituição de outra (ex.: "ITAU S.A." vs "ITAU LTDA").
SUFIXOS_EMPRESARIAIS = re.compile(
    r"\b(S\s*A|S\s*A\s*S|LTDA|LIMITADA|BANCO|BANCOS|BCO|BCOS|FINANCEIRA|"
    r"CONGLOMERADO|PRUDENCIAL|GRUPO|HOLDING|INSTITUICAO|INSTITUICOES)\b"
)


def normalizar_nome(nome) -> str:
    """Normaliza um nome de instituição para comparação fuzzy:
    maiúsculas, sem acentos, sem pontuação, sem sufixos societários
    comuns e com espaços únicos. Retorna string vazia para nulos."""
    if nome is None or (isinstance(nome, float) and pd.isna(nome)):
        return ""
    texto = str(nome).upper().strip()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = SUFIXOS_EMPRESARIAIS.sub(" ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def melhor_correspondencia(nome_norm: str, candidatos: list, score_minimo: int = 88):
    """Retorna (candidato, score 0-100) com a melhor correspondência
    aproximada de `nome_norm` em `candidatos`, ou (None, 0) se nada
    atingir `score_minimo`. `token_sort_ratio` ignora a ordem das
    palavras, o que ajuda bastante com nomes de bancos/empresas."""
    if not nome_norm or not candidatos:
        return None, 0
    resultado = process.extractOne(
        nome_norm, candidatos, scorer=fuzz.token_sort_ratio, score_cutoff=score_minimo
    )
    if resultado is None:
        return None, 0
    candidato, score, _ = resultado
    return candidato, score


def resolver_pendentes_por_fuzzy(
    df: pd.DataFrame,
    mascara_pendente: pd.Series,
    coluna_nome_origem: str,
    lookup: pd.DataFrame,
    coluna_nome_lookup: str,
    colunas_retorno: dict,
    score_minimo: int = 88,
) -> pd.DataFrame:
    """
    Preenche, apenas nas linhas de `df` marcadas por `mascara_pendente`,
    as colunas listadas em `colunas_retorno` usando fuzzy match do nome
    normalizado (coluna `coluna_nome_origem`) contra `lookup[coluna_nome_lookup]`
    (já deve estar normalizado com `normalizar_nome`).

    colunas_retorno: dict {coluna_no_lookup: coluna_no_df_destino}
        ex.: {"cnpj": "cnpj_resolvido"}

    Adiciona duas colunas de auditoria (só nas linhas resolvidas por
    fuzzy): "<coluna_nome_origem>_fuzzy_candidato" e
    "<coluna_nome_origem>_fuzzy_score", para permitir revisão manual
    dos casos de menor confiança.
    """
    df = df.copy()
    col_candidato = f"{coluna_nome_origem}_fuzzy_candidato"
    col_score = f"{coluna_nome_origem}_fuzzy_score"
    if col_candidato not in df.columns:
        df[col_candidato] = pd.NA
    if col_score not in df.columns:
        df[col_score] = pd.NA

    candidatos = lookup[coluna_nome_lookup].dropna().unique().tolist()
    lookup_indexado = lookup.drop_duplicates(subset=coluna_nome_lookup).set_index(coluna_nome_lookup)

    for idx in df.index[mascara_pendente]:
        nome_norm = df.at[idx, coluna_nome_origem]
        candidato, score = melhor_correspondencia(nome_norm, candidatos, score_minimo)
        if candidato is None:
            continue
        linha = lookup_indexado.loc[candidato]
        for col_lookup, col_destino in colunas_retorno.items():
            df.at[idx, col_destino] = linha[col_lookup]
        df.at[idx, col_candidato] = candidato
        df.at[idx, col_score] = score

    return df
