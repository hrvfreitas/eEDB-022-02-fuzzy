"""
ETAPA 3 - UNIÃO E ENTREGA (CAMADA DELIVERY)
==============================================
Lê as três bases já tratadas na camada Trusted (a partir dos arquivos
Parquet em disco) e as une (com pandas, sem SQL) em uma única tabela final,
na granularidade "banco x trimestre":

    Reclamações (nível Banco/financeira, que possui CNPJ)
        LEFT JOIN Bancos (segmento oficial / nome oficial)   -- por CNPJ
        LEFT JOIN Empregados Glassdoor (avaliações dos funcionários) -- por CNPJ

Somente as linhas de Reclamações cujo CNPJ pôde ser resolvido entram na
tabela final -- seja porque já vinham com CNPJ na origem ("Banco/financeira"),
seja porque o CNPJ foi resolvido na camada Trusted a partir do nome do
conglomerado (ex.: "BRADESCO (conglomerado)" -> CNPJ do Bradesco). Ficam de
fora apenas os que não constam na base de enquadramento de Bancos
(principalmente fintechs/instituições de pagamento, ex.: Nubank, Stone,
Inter), que permanecem disponíveis na camada Trusted para outras análises.

O resultado final é salvo em Parquet (data/delivery/) e carregado no banco
de dados relacional como a tabela final (schema "delivery").
"""
import os                     # Para manipulação de caminhos e pastas

import pandas as pd           # Para manipulação de dados tabulares

from db import get_engine     # Importa a função que cria a conexão com o PostgreSQL

# Define o diretório onde estão os dados da camada Trusted (Parquet)
TRUSTED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "trusted")
# Define o diretório onde serão salvos os dados da camada Delivery (Parquet final)
DELIVERY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "delivery")
# Cria o diretório de delivery (e subpastas) caso não exista
os.makedirs(DELIVERY_DIR, exist_ok=True)


def montar_delivery(reclamacoes: pd.DataFrame, bancos: pd.DataFrame, empregados: pd.DataFrame) -> pd.DataFrame:
    """
    Função que une as três bases tratadas (Reclamações, Bancos, Empregados)
    em uma única tabela final, na granularidade banco x trimestre.
    Retorna o DataFrame final com todas as colunas.
    """
    # Entram na tabela final todos os registros cujo CNPJ pôde ser resolvido
    # (seja diretamente na origem, para "Banco/financeira", seja por meio do
    # nome do conglomerado, para os grandes bancos "Conglomerado")
    # Filtra apenas as linhas de reclamações que têm CNPJ não nulo
    base = reclamacoes[reclamacoes["cnpj"].notna()].copy()

    # Faz um LEFT JOIN com a base de Bancos para trazer segmento e nomes oficiais/alternativos
    # Usa o CNPJ como chave de junção. Sufixo "_bancos" para colunas que possam ter nome igual
    base = base.merge(
        bancos[["cnpj", "segmento", "nome_banco", "nome_alternativo"]],
        on="cnpj",
        how="left",
        suffixes=("", "_bancos"),
    )

    # Prepara a lista de colunas do Glassdoor que serão trazidas (exceto CNPJ, segmento, origem_match)
    colunas_glassdoor = [c for c in empregados.columns if c not in ("cnpj", "segmento", "origem_match")]
    # Faz um LEFT JOIN com a base de Empregados Glassdoor (também por CNPJ)
    # Sufixo "_glassdoor" para distinguir colunas que possam ter nomes iguais
    base = base.merge(
        empregados[["cnpj", "origem_match"] + colunas_glassdoor],
        on="cnpj",
        how="left",
        suffixes=("", "_glassdoor"),
    )

    # Renomeia colunas para melhor clareza: "segmento" da base de Reclamações (na verdade veio do merge com Bancos) vira "segmento_bacen"
    # e "origem_match" (do Glassdoor) vira "origem_match_glassdoor"
    base = base.rename(
        columns={
            "segmento": "segmento_bacen",
            "origem_match": "origem_match_glassdoor",
        }
    )

    # Cria coluna booleana indicando se há avaliação do Glassdoor associada (baseado em "employer_name" preenchido)
    base["possui_avaliacao_glassdoor"] = base["employer_name"].notna()

    # Define a ordem final das colunas na tabela final (para padronização e legibilidade)
    colunas_ordem = [
        "ano",
        "trimestre",
        "cnpj",
        "cnpj_origem",
        "instituicao_financeira",
        "nome_banco",
        "nome_alternativo",
        "segmento_bacen",
        "categoria",
        "indice",
        "qtd_reclamacoes_reguladas_procedentes",
        "qtd_reclamacoes_reguladas_outras",
        "qtd_reclamacoes_nao_reguladas",
        "qtd_total_reclamacoes",
        "qtd_total_clientes_ccs_scr",
        "qtd_clientes_ccs",
        "qtd_clientes_scr",
        "possui_avaliacao_glassdoor",
        "employer_name",
        "reviews_count",
        "culture_count",
        "salaries_count",
        "benefits_count",
        "employer_website",
        "employer_headquarters",
        "employer_founded",
        "employer_industry",
        "employer_revenue",
        "url",
        "nota_geral",
        "nota_cultura_valores",
        "nota_diversidade_inclusao",
        "nota_qualidade_vida",
        "nota_alta_lideranca",
        "nota_remuneracao_beneficios",
        "nota_oportunidades_carreira",
        "pct_recomendam_empresa",
        "pct_perspectiva_positiva",
        "match_percent",
        "origem_match_glassdoor",
    ]

    # Seleciona apenas as colunas na ordem definida, ordena os registros por ano, trimestre e instituição
    delivery = base[colunas_ordem].sort_values(by=["ano", "trimestre", "instituicao_financeira"]).reset_index(drop=True)
    return delivery


def main():
    """
    Função principal: lê os Parquet da camada Trusted, monta a tabela final,
    salva em Parquet na camada Delivery e carrega no PostgreSQL.
    """
    # Lê os arquivos Parquet da camada Trusted
    print("Lendo camada Trusted (Parquet)...")
    reclamacoes = pd.read_parquet(os.path.join(TRUSTED_DIR, "reclamacoes.parquet"))
    bancos = pd.read_parquet(os.path.join(TRUSTED_DIR, "bancos.parquet"))
    empregados = pd.read_parquet(os.path.join(TRUSTED_DIR, "empregados_glassdoor.parquet"))

    print("Unindo as bases (Reclamações + Bancos + Empregados Glassdoor) via CNPJ...")
    delivery = montar_delivery(reclamacoes, bancos, empregados)
    print(f"  -> tabela final com {len(delivery)} linhas e {len(delivery.columns)} colunas")
    print(f"  -> {delivery['possui_avaliacao_glassdoor'].sum()} linhas possuem avaliação Glassdoor associada")

    # Salva a tabela final em Parquet dentro da pasta delivery
    caminho_parquet = os.path.join(DELIVERY_DIR, "delivery_reclamacoes_bancos_funcionarios.parquet")
    print(f"\nSalvando camada Delivery em Parquet: {caminho_parquet}")
    delivery.to_parquet(caminho_parquet, index=False)

    # Carrega a tabela final no banco PostgreSQL, schema delivery
    print("Carregando tabela final no banco relacional (schema 'delivery')...")
    engine = get_engine()
    with engine.begin() as conn:   # Inicia uma transação
        # Cria o schema delivery se ainda não existir
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS delivery;")

    # Escreve o DataFrame na tabela 'tb_reclamacoes_bancos_funcionarios', substituindo se já existir
    delivery.to_sql(
        "tb_reclamacoes_bancos_funcionarios",
        engine,
        schema="delivery",
        if_exists="replace",
        index=False,
    )
    print("Camada Delivery concluída com sucesso.")
    print("Tabela final disponível em: delivery.tb_reclamacoes_bancos_funcionarios")


# Se o script for executado diretamente, chama a função main
if __name__ == "__main__":
    main()
