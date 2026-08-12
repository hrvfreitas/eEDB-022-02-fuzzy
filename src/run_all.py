"""
Orquestrator: RAW -> Trusted -> Delivery.

Uso:
    python3 run_all.py
"""
import subprocess   # Para executar outros scripts Python como processos separados
import sys          # Para acessar argumentos do sistema e finalizar com código de erro
import os           # Para manipular caminhos de arquivos

# Importa a função que aguarda o PostgreSQL ficar disponível (definida em db.py)
from db import wait_for_db

# Obtém o diretório onde este script está localizado (para construir caminhos relativos)
DIR = os.path.dirname(__file__)

# Lista com os nomes dos scripts que compõem as etapas do pipeline, na ordem de execução
ETAPAS = ["01_ingest_raw.py", "02_trusted.py", "03_delivery.py"]

# Se este script for executado diretamente (não importado como módulo)
if __name__ == "__main__":
    # Aguarda o banco de dados PostgreSQL estar pronto para aceitar conexões
    # (útil quando executado em containers Docker que podem iniciar em ordens diferentes)
    wait_for_db()

    # Itera sobre cada etapa do pipeline
    for etapa in ETAPAS:
        # Imprime um separador visual e o nome da etapa sendo executada
        print("\n" + "=" * 70)
        print(f"EXECUTANDO: {etapa}")
        print("=" * 70)
        # Executa o script da etapa atual como um subprocesso separado
        # Usa o mesmo interpretador Python que está rodando este script (sys.executable)
        # e passa o caminho completo do script (junção de DIR com o nome da etapa)
        resultado = subprocess.run([sys.executable, os.path.join(DIR, etapa)])
        # Verifica se a execução do script retornou código de erro (diferente de 0)
        if resultado.returncode != 0:
            print(f"\nErro ao executar {etapa}")
            # Finaliza este orquestrador com código de erro 1 (indicando falha)
            sys.exit(1)
    # Se todas as etapas foram executadas com sucesso, imprime mensagem de conclusão
    print("\n" + "=" * 70)
    print("CONCLUÍDO COM SUCESSO")
    print("=" * 70)
