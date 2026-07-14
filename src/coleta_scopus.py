"""Coleta na Scopus Search API a produção da UFRN de um ano.

    python3 src/coleta_scopus.py --ano 2020 --saida /caminho/dados/scopus-2020.csv

O universo da UFRN na Scopus é a **união de duas consultas**, executadas separadamente
e unidas aqui, com deduplicação por EID:

    AF-ID(60023857) AND PUBYEAR IS <ano>
    AFFILORG("Universidade Federal do Rio Grande do Norte") AND PUBYEAR IS <ano>

A segunda existe porque a primeira não basta. O ``AF-ID`` recupera o que a Scopus
vinculou ao perfil de afiliação da instituição, e parte dos registros traz a afiliação
"Universidade Federal do Rio Grande do Norte" **sem** identificador de afiliação
atribuído (o campo ``afid`` vem nulo), tipicamente por atraso do processamento nos
registros mais recentes. Esses registros são invisíveis à consulta por AF-ID. Medido
em 14/07/2026: 6 registros em 2023 e 12 em 2025, isto é, o vazamento cresce nos anos
recentes. Coletar só pelo AF-ID encolheria o denominador do estudo e, como esses
registros quase nunca estão no repositório, **superestimaria a cobertura** — viés
contra a hipótese, mas viés.

A união é feita aqui, e não na query, porque o parser da Scopus não a honra: a consulta
``(AF-ID(...) OR AFFILORG(...))`` devolve o mesmo total da consulta por AF-ID sozinha, e
``... AND NOT AF-ID(...)`` ignora o recorte de ano. Duas consultas e uma união local é o
único caminho que se pode conferir.

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
NOME_ORG = "Universidade Federal do Rio Grande do Norte"
CONTAGEM = 25  # máximo permitido para esta chave
JANELA = 5000  # teto de start imposto pela Scopus
FONTE = "scopus"

# as duas vias de recuperação da afiliação, unidas por EID (ver docstring do módulo).
# O rótulo identifica a fatia no diretório raw/, de modo que as respostas de uma via não
# sobrescrevam as da outra e a coleta siga resumível.
VIAS = (
    ("perfil", f"AF-ID({AF_ID})"),
    ("nome", f'AFFILORG("{NOME_ORG}")'),
)


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
    """União das duas vias de afiliação, deduplicada por EID."""
    chave = carregar_chave("API_KEY_SCOPUS")
    cabecalhos = {"X-ELS-APIKey": chave}

    registros: list[dict] = []
    vistos: set[str] = set()
    for via, clausula in VIAS:
        novos = 0
        for r in coletar_via(ano, via, clausula, saida, cabecalhos, refazer):
            if r["source_id"] in vistos:
                continue
            vistos.add(r["source_id"])
            registros.append(r)
            novos += 1
        print(f"  via {via}: {novos} registros novos (acumulado {len(registros)})")

    escrever_csv(saida, registros)
    return registros


def coletar_via(
    ano: int, via: str, clausula: str, saida: str, cabecalhos: dict, refazer: bool
) -> list[dict]:
    """Percorre a paginação de uma das duas consultas de afiliação."""
    query = f"{clausula} AND PUBYEAR IS {ano}"
    fatia = f"{ano}-{via}"

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
            print(f"{ano} ({via}): {total} registros anunciados pela Scopus")
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
    return registros


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ano", type=int, required=True)
    p.add_argument("--saida", required=True)
    p.add_argument("--refazer", action="store_true", help="ignora as respostas já salvas em raw/")
    a = p.parse_args()
    coletar(a.ano, a.saida, a.refazer)
