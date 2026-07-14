"""Coleta no Repositório Institucional da UFRN (DSpace 7, API REST pública).

    python3 src/coleta_ri.py --ano 2020 --saida /caminho/dados/ri-2020.csv
    python3 src/coleta_ri.py --de 1960 --ate 2026 --dados /caminho/dados

Baixa o universo de itens do repositório com data de publicação no ano, um CSV por
ano, no mesmo formato das duas bases. O pareamento é feito depois, localmente,
sobre esses arquivos: consultar o repositório registro a registro multiplicaria as
requisições e produziria falso negativo por variação de grafia.

O repositório é coletado em toda a sua extensão temporal, e não apenas no recorte
2020–2025 do estudo, porque ele é o lado *candidato* do pareamento. O recorte
delimita o universo das bases, que é o que se mede; restringi-lo também do lado do
repositório faria o artigo depositado com data divergente da data de publicação na
base contar como ausente, e a defasagem seria superestimada. O ano do depósito é
irrelevante, em particular, para o pareamento por DOI: um DOI encontrado no
repositório prova que o item está lá, qualquer que seja a data registrada.

A coleta é fatiada por ano também porque a busca Discovery roda sobre Solr, e a
paginação profunda sobre dezenas de milhares de itens é onde ela falha.

O DOI é procurado por expressão regular em todos os campos dc.identifier.*, e não
apenas em dc.identifier.doi: em amostra de 500 itens do período, entre os 32
artigos, 29 traziam o DOI em dc.identifier.doi, mas outros dois só o traziam em
dc.identifier.citation ou dc.identifier.other.
"""

from __future__ import annotations

import argparse
import os
import time

from common import (
    CAMPOS_RI,
    caminho_raw,
    escrever_csv,
    get_json,
    ler_raw,
    normalizar_doi,
    salvar_raw,
)

URL = "https://repositorio.ufrn.br/server/api/discover/search/objects"
TAMANHO = 100  # máximo aceito pelo servidor
PAUSA = 0.5  # cortesia; a API pública não impõe limite formal
FONTE = "ri"


def _primeiro(metadados: dict, campo: str) -> str:
    valores = metadados.get(campo) or []
    return (valores[0].get("value") or "").strip() if valores else ""


def _doi(metadados: dict) -> str:
    """Procura o DOI em dc.identifier.doi e, se não achar, nos demais identificadores."""
    doi = normalizar_doi(_primeiro(metadados, "dc.identifier.doi"))
    if doi:
        return doi
    for campo, valores in metadados.items():
        if not campo.startswith("dc.identifier"):
            continue
        for valor in valores:
            doi = normalizar_doi(valor.get("value"))
            if doi:
                return doi
    return ""


def extrair(item: dict) -> dict:
    md = item.get("metadata") or {}
    return {
        "source_id": item.get("uuid", ""),
        "doi": _doi(md),
        "title": _primeiro(md, "dc.title"),
        "year": _primeiro(md, "dc.date.issued")[:4],
        "type": _primeiro(md, "dc.type"),
        "venue": "",
        "issn": "",
        "handle": item.get("handle", ""),
    }


def coletar(ano: int, saida: str, refazer: bool) -> list[dict]:
    registros: list[dict] = []
    pagina = 0
    total_paginas = None
    fatia = str(ano)

    while True:
        payload = None if refazer else ler_raw(saida, FONTE, fatia, pagina)
        if payload is None:
            payload = get_json(
                URL,
                {
                    "dsoType": "item",
                    "f.dateIssued": f"[{ano} TO {ano}],equals",
                    "size": TAMANHO,
                    "page": pagina,
                },
            )
            salvar_raw(saida, FONTE, fatia, pagina, payload)
            time.sleep(PAUSA)
        else:
            print(f"  página {pagina} já em {caminho_raw(saida, FONTE, fatia, pagina)}")

        resultado = payload["_embedded"]["searchResult"]
        info = resultado["page"]
        if total_paginas is None:
            total_paginas = info["totalPages"]
            print(f"{ano}: {info['totalElements']} itens no RI ({total_paginas} páginas)")

        objetos = (resultado.get("_embedded") or {}).get("objects") or []
        for objeto in objetos:
            registros.append(extrair(objeto["_embedded"]["indexableObject"]))

        pagina += 1
        if not objetos or pagina >= total_paginas:
            break

    escrever_csv(saida, registros, CAMPOS_RI)
    return registros


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ano", type=int, help="coleta um único ano (exige --saida)")
    p.add_argument("--de", type=int, help="primeiro ano de um intervalo (exige --dados)")
    p.add_argument("--ate", type=int, help="último ano do intervalo")
    p.add_argument("--saida", help="CSV de saída, no modo --ano")
    p.add_argument("--dados", help="diretório de saída, no modo --de/--ate")
    p.add_argument("--refazer", action="store_true", help="ignora as respostas já salvas em raw/")
    a = p.parse_args()

    if a.ano is not None:
        if not a.saida:
            p.error("--ano exige --saida")
        coletar(a.ano, a.saida, a.refazer)
    elif a.de is not None and a.ate is not None:
        if not a.dados:
            p.error("--de/--ate exigem --dados")
        for ano in range(a.de, a.ate + 1):
            # ano sem item nenhum custa uma requisição e nenhum arquivo; a extensão
            # temporal do repositório não é conhecida de antemão
            registros = coletar(ano, os.path.join(a.dados, f"ri-{ano}.csv"), a.refazer)
            if not registros:
                os.remove(os.path.join(a.dados, f"ri-{ano}.csv"))
    else:
        p.error("informe --ano ou --de/--ate")
