"""Data de depósito dos itens do repositório, extraída das respostas já coletadas.

    python3 src/deposito.py --dados /caminho/dados

O CSV do repositório guarda a data de *publicação* (``dc.date.issued``), que é a que
o pareamento usa. A data de *depósito* (``dc.date.accessioned``) responde a outra
pergunta, e é ela que este script recupera: **quando** o item entrou no repositório.

A distinção importa porque a cobertura por ano de publicação não decresce de forma
monótona — cai de 2020 a 2024 e sobe de novo em 2025 —, e a explicação candidata é de
processo, não de publicação: o repositório recebeu, num intervalo curto, uma carga de
artigos recentes. Só a data de depósito decide isso. Sem ela, a interpretação da série
temporal seria conjectura.

Não há requisição nova: as respostas da API estão gravadas em ``dados/raw/ri-*.json``
desde a fase 1, e o campo está lá, apenas não foi levado para o CSV.

Somente biblioteca padrão.
"""

from __future__ import annotations

import argparse
import glob
import json
import os

from common import escrever_csv

CAMPOS_DEPOSITO = ["source_id", "handle", "ano_publicacao", "ano_deposito", "data_deposito"]


def _primeiro(metadados: dict, campo: str) -> str:
    valores = metadados.get(campo) or []
    return (valores[0].get("value") or "").strip() if valores else ""


def extrair(item: dict) -> dict:
    md = item.get("metadata") or {}
    deposito = _primeiro(md, "dc.date.accessioned")
    return {
        "source_id": item.get("uuid", ""),
        "handle": item.get("handle", ""),
        "ano_publicacao": _primeiro(md, "dc.date.issued")[:4],
        "ano_deposito": deposito[:4],
        "data_deposito": deposito,
    }


def executar(dados: str) -> None:
    arquivos = sorted(glob.glob(os.path.join(dados, "raw", "ri-*.json")))
    if not arquivos:
        raise SystemExit(f"nenhuma resposta do repositório em {os.path.join(dados, 'raw')}")

    registros: dict[str, dict] = {}
    sem_data = 0
    for caminho in arquivos:
        with open(caminho, encoding="utf-8") as f:
            payload = json.load(f)
        resultado = payload["_embedded"]["searchResult"]
        objetos = (resultado.get("_embedded") or {}).get("objects") or []
        for objeto in objetos:
            registro = extrair(objeto["_embedded"]["indexableObject"])
            if not registro["source_id"]:
                continue
            if not registro["ano_deposito"]:
                sem_data += 1
            # o mesmo item aparece uma vez só, mas as fatias anuais foram recoletadas
            # em datas diferentes; a chave é o uuid, e a repetição é idêntica
            registros[registro["source_id"]] = registro

    if sem_data:
        print(f"AVISO: {sem_data} itens sem dc.date.accessioned")

    escrever_csv(
        os.path.join(dados, "deposito-ri.csv"),
        sorted(registros.values(), key=lambda r: (r["ano_deposito"], r["source_id"])),
        CAMPOS_DEPOSITO,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com as respostas cruas em raw/")
    a = p.parse_args()
    executar(a.dados)
