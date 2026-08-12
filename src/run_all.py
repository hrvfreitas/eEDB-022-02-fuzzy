"""
Orquestrator: RAW -> Trusted -> Delivery.

Uso:
    python3 run_all.py
"""
import subprocess
import sys
import os

from db import wait_for_db

DIR = os.path.dirname(__file__)

ETAPAS = ["01_ingest_raw.py", "02_trusted.py", "03_delivery.py"]

if __name__ == "__main__":
    wait_for_db()

    for etapa in ETAPAS:
        print("\n" + "=" * 70)
        print(f"EXECUTANDO: {etapa}")
        print("=" * 70)
        resultado = subprocess.run([sys.executable, os.path.join(DIR, etapa)])
        if resultado.returncode != 0:
            print(f"\nErro ao executar {etapa}")
            sys.exit(1)
    print("\n" + "=" * 70)
    print("CONCLUÍDO COM SUCESSO")
    print("=" * 70)
