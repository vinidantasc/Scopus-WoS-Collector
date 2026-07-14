"""Coleta na Scopus Search API a produção da UFRN de um ano.

    python3 src/coleta_scopus.py --ano 2020 --saida /caminho/dados/scopus-2020.csv

Query: AF-ID(60023857) AND PUBYEAR IS <ano>, view STANDARD. AF-ID 60023857 é o
identificador de afiliação da UFRN na Scopus.

Paginação por deslocamento (start/count), e não por cursor: a chave usada não tem
direito ao parâmetro cursor, que devolve 403 (ENTITLEMENTS_ERROR), e o teto de
count neste nível de serviço é 25. O recurso ao deslocamento é seguro aqui porque
a janela de resultados da Scopus vai até 5.000 e nenhuma fatia anual da UFRN passa
de aproximadamente 2.100 registros. Isso é o que obriga a fatiar a coleta por ano.
"""

from __future__ import annotations

import argparse

from common import (
    caminho_raw,
    carregar_chave,
    escrever_csv,
    get_json,
    ler_raw,
    normalizar_doi,
    salvar_raw,
)

URL = "https://api.elsevier.com/content/search/scopus"
AF_ID = "60023857"  # UFRN
CONTAGEM = 25  # máximo permitido para esta chave
JANELA = 5000  # teto de start imposto pela Scopus
FONTE = "scopus"


def extrair(entry: dict) -> dict:
    data = entry.get("prism:coverDate", "")
    return {
        "source_id": entry.get("eid", ""),
        "doi": normalizar_doi(entry.get("prism:doi")),
        "title": (entry.get("dc:title") or "").strip(),
        "year": data[:4],
        "type": entry.get("subtypeDescription", ""),
        "venue": entry.get("prism:publicationName", ""),
        "issn": entry.get("prism:issn", ""),
    }


def coletar(ano: int, saida: str, refazer: bool) -> list[dict]:
    chave = carregar_chave("API_KEY_SCOPUS")
    cabecalhos = {"X-ELS-APIKey": chave}
    query = f"AF-ID({AF_ID}) AND PUBYEAR IS {ano}"
    fatia = str(ano)

    registros: list[dict] = []
    pagina = 0
    total = None

    while True:
        inicio = pagina * CONTAGEM
        payload = None if refazer else ler_raw(saida, FONTE, fatia, pagina)
        if payload is None:
            payload = get_json(
                URL,
                {"query": query, "view": "STANDARD", "count": CONTAGEM, "start": inicio},
                cabecalhos,
            )
            salvar_raw(saida, FONTE, fatia, pagina, payload)
        else:
            print(f"  página {pagina} já em {caminho_raw(saida, FONTE, fatia, pagina)}")

        resultados = payload["search-results"]
        if total is None:
            total = int(resultados.get("opensearch:totalResults", 0))
            print(f"{ano}: {total} registros na Scopus")
            if total > JANELA:
                raise SystemExit(
                    f"{ano}: {total} registros excedem a janela de {JANELA} da Scopus; "
                    "fatiar a query em recortes menores que um ano"
                )

        entradas = resultados.get("entry") or []
        if len(entradas) == 1 and "error" in entradas[0]:
            break
        for entrada in entradas:
            registros.append(extrair(entrada))

        pagina += 1
        if not entradas or pagina * CONTAGEM >= total:
            break

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
