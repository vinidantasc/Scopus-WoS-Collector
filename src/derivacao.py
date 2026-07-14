"""Evidência de derivação entre o registro ausente e a tese/TCC achada no repositório.

    python3 src/derivacao.py --dados /caminho/dados

Para cada registro do estrato dos ausentes que a triagem (`src/triagem.py`) associou
a um trabalho acadêmico no repositório, baixa o **metadado completo** do item e
escreve `dados/derivacao-ausentes.csv`. A pergunta que o conferente responde com
esse arquivo é uma só: a tese, a dissertação ou o TCC depositado é o trabalho de
onde saiu o artigo, ou é outro trabalho do mesmo autor?

O que se busca no item do repositório, e por quê:

- **título alternativo** (`dc.title.alternative`) — o depósito muitas vezes traz o
  título em inglês, que é o do artigo. Quando existe, resolve o caso sozinho.
- **resumo e abstract** (`dc.description.abstract`) — descrevem o objeto do
  trabalho, e permitem ver se é o mesmo estudo do artigo.
- **autor e orientador** (`dc.contributor.*`) — o autor do trabalho acadêmico é,
  em regra, o primeiro autor do artigo; o orientador costuma ser coautor.
- **identificadores** (`dc.identifier.*`) — parte dos depósitos traz o DOI do
  artigo derivado dentro da citação.
- **link do PDF** (bitstream) — para os casos que o metadado não resolve.

O script não decide a derivação: nenhuma medida automática o faz, porque o título
vertido para o português tem, contra o título em inglês do artigo, a mesma
similaridade de dois trabalhos sem relação alguma. Ele reúne o que é preciso ler.
"""

from __future__ import annotations

import argparse
import os
import time

from common import escrever_csv, get_json, ler_csv

URL_BUSCA = "https://repositorio.ufrn.br/server/api/discover/search/objects"
PAUSA = 0.5

CAMPOS = [
    "fonte",
    "id_base",
    "titulo_base",
    "ano_base",
    "doi_base",
    "handle_ri",
    "tipo_ri",
    "titulo_ri",
    "titulo_alternativo_ri",
    "ano_ri",
    "autores_ri",
    "orientador_ri",
    "identificadores_ri",
    "resumo_ri",
    "pdf_ri",
]


def _valores(metadados: dict, campo: str) -> list[str]:
    return [(v.get("value") or "").strip() for v in (metadados.get(campo) or [])]


def _um(metadados: dict, campo: str) -> str:
    valores = _valores(metadados, campo)
    return valores[0] if valores else ""


def item_por_handle(handle: str) -> dict:
    """Metadado completo do item, pela busca Discovery (a API pública não expõe
    o item por handle sem o uuid)."""
    payload = get_json(URL_BUSCA, {"query": f'handle:"{handle}"', "size": 5, "dsoType": "item"})
    time.sleep(PAUSA)
    objetos = (
        payload.get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )
    for objeto in objetos:
        item = objeto.get("_embedded", {}).get("indexableObject", {}) or {}
        if (item.get("handle") or "") == handle:
            return item
    return {}


def pdf_do_item(uuid: str) -> str:
    """URL do primeiro bitstream do pacote ORIGINAL, quando houver."""
    if not uuid:
        return ""
    url = f"https://repositorio.ufrn.br/server/api/core/items/{uuid}/bundles"
    try:
        bundles = get_json(url, {})
    except Exception:
        return ""
    time.sleep(PAUSA)
    for bundle in bundles.get("_embedded", {}).get("bundles", []) or []:
        if (bundle.get("name") or "") != "ORIGINAL":
            continue
        href = bundle.get("_links", {}).get("bitstreams", {}).get("href", "")
        if not href:
            continue
        try:
            bitstreams = get_json(href, {})
        except Exception:
            return ""
        time.sleep(PAUSA)
        for bit in bitstreams.get("_embedded", {}).get("bitstreams", []) or []:
            conteudo = bit.get("_links", {}).get("content", {}).get("href", "")
            if conteudo:
                return conteudo
    return ""


def executar(dados: str) -> None:
    amostra = ler_csv(os.path.join(dados, "validacao-manual.csv"))
    alvos = [
        l
        for l in amostra
        if l["estrato"] == "ausente" and "/handle/" in l.get("url_alvo", "")
    ]
    print(f"itens acadêmicos a detalhar: {len(alvos)}")

    linhas = []
    for i, linha in enumerate(alvos, 1):
        handle = linha["url_alvo"].rsplit("/handle/", 1)[-1]
        item = item_por_handle(handle)
        metadados = item.get("metadata", {}) or {}
        identificadores = []
        for campo, valores in metadados.items():
            if campo.startswith("dc.identifier"):
                identificadores += [f"{campo}={v.get('value')}" for v in valores]
        linhas.append(
            {
                "fonte": linha["fonte"],
                "id_base": linha["id_base"],
                "titulo_base": linha["titulo_base"],
                "ano_base": linha["ano_base"],
                "doi_base": linha["url_base"].replace("https://doi.org/", ""),
                "handle_ri": handle,
                "tipo_ri": _um(metadados, "dc.type"),
                "titulo_ri": _um(metadados, "dc.title"),
                "titulo_alternativo_ri": " | ".join(_valores(metadados, "dc.title.alternative")),
                "ano_ri": _um(metadados, "dc.date.issued")[:4],
                "autores_ri": " | ".join(_valores(metadados, "dc.contributor.author")),
                "orientador_ri": " | ".join(_valores(metadados, "dc.contributor.advisor")),
                "identificadores_ri": " | ".join(identificadores),
                "resumo_ri": " ".join(_valores(metadados, "dc.description.abstract"))[:3000],
                "pdf_ri": pdf_do_item(item.get("uuid", "")),
            }
        )
        print(f"  [{i:2d}/{len(alvos)}] {handle} {linhas[-1]['tipo_ri']}")

    caminho = os.path.join(dados, "derivacao-ausentes.csv")
    escrever_csv(caminho, linhas, CAMPOS)
    print(f"\ngravado: {caminho}")


def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", required=True)
    executar(parser.parse_args().dados)


if __name__ == "__main__":
    principal()
