"""Coleta na Web of Science Starter API a produção da UFRN de um ano.

    python3 src/coleta_wos.py --ano 2020 --saida /caminho/dados/wos-2020.csv

Query: OG=(Universidade Federal do Rio Grande do Norte) AND PY=<ano>, base WOS
(Core Collection), paginação page/limit com limit=50 (máximo da API).

A variante do nome da organização foi fixada por comparação de totais no período
2020-2025: o nome por extenso recupera 11.271 registros e a forma abreviada
(Univ Fed Rio Grande do Norte) recupera 9.548. Adotou-se o nome por extenso.
"""

from __future__ import annotations

import argparse
import time

from common import (
    caminho_raw,
    carregar_chave,
    escrever_csv,
    get_json,
    ler_raw,
    normalizar_doi,
    salvar_raw,
)

URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"
ORGANIZACAO = "Universidade Federal do Rio Grande do Norte"
LIMITE = 50  # máximo da Starter API
PAUSA = 0.25  # respeita o teto de 5 requisições por segundo
FONTE = "wos"


def extrair(hit: dict) -> dict:
    fonte = hit.get("source") or {}
    ids = hit.get("identifiers") or {}
    tipos = hit.get("types") or []
    return {
        "source_id": hit.get("uid", ""),
        "doi": normalizar_doi(ids.get("doi")),
        "title": (hit.get("title") or "").strip(),
        "year": str(fonte.get("publishYear", "")),
        "type": "; ".join(tipos),
        "venue": fonte.get("sourceTitle", ""),
        "issn": ids.get("issn", ""),
    }


def coletar(ano: int, saida: str, refazer: bool) -> list[dict]:
    chave = carregar_chave("API_KEY_WOS")
    cabecalhos = {"X-ApiKey": chave}
    query = f"OG=({ORGANIZACAO}) AND PY={ano}"
    fatia = str(ano)

    registros: list[dict] = []
    pagina = 1
    total = None

    while True:
        payload = None if refazer else ler_raw(saida, FONTE, fatia, pagina)
        if payload is None:
            payload = get_json(
                URL,
                {"q": query, "db": "WOS", "limit": LIMITE, "page": pagina},
                cabecalhos,
            )
            salvar_raw(saida, FONTE, fatia, pagina, payload)
            time.sleep(PAUSA)
        else:
            print(f"  página {pagina} já em {caminho_raw(saida, FONTE, fatia, pagina)}")

        if total is None:
            total = int(payload["metadata"]["total"])
            print(f"{ano}: {total} registros na WoS")

        hits = payload.get("hits") or []
        for hit in hits:
            registros.append(extrair(hit))

        if not hits or pagina * LIMITE >= total:
            break
        pagina += 1

    if total is not None and len(registros) != total:
        print(f"  ATENÇÃO: coletados {len(registros)}, total anunciado {total}")
    escrever_csv(saida, registros)
    return registros


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ano", type=int, required=True)
    p.add_argument("--saida", required=True)
    p.add_argument("--refazer", action="store_true", help="ignora as respostas já salvas em raw/")
    a = p.parse_args()
    coletar(a.ano, a.saida, a.refazer)
