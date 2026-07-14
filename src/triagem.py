"""Triagem assistida da amostra de conferência da fase 2.

    python3 src/triagem.py --dados /caminho/dados

Instrui a conferência manual: para cada registro sorteado no estrato dos
**ausentes** (`validacao-manual.csv`), reúne a evidência que o conferente
precisaria buscar à mão e a grava numa coluna. O veredito continua sendo dado por
pessoa, item a item; o script não decide nada, apenas mostra o que encontrou.

O estrato dos ausentes é o que mede o **falso negativo** do protocolo: o trabalho
está no repositório, mas o pareamento não o achou (título traduzido, DOI grafado
fora do padrão, depósito sem DOI). Confirmá-lo exige procurar o trabalho no
repositório por caminhos que o pareamento não usa. São quatro buscas por registro:

1. **DOI no índice de busca do repositório** — a busca Discovery varre todos os
   campos de metadado, inclusive os que a coleta lê por expressão regular. Um
   acerto aqui significa que o DOI está no item, mas em campo que a coleta não
   alcançou, e o par existia.
2. **Título como frase** — acha o depósito cujo título difere por pontuação,
   subtítulo ou grafia, abaixo do limiar de 0,95 da etapa M3.
3. **Nome do primeiro autor** — o único caminho que acha o **título traduzido**,
   caso em que nenhuma busca por título funciona. Os títulos dos itens do autor no
   repositório são comparados por similaridade com o título da base.
4. **Varredura local do repositório inteiro** (`ri-todos.csv`, 54.450 itens), por
   similaridade de título sem limiar, para expor o vizinho mais próximo mesmo
   quando ele fica longe do corte.

A sugestão gravada é conservadora: só chama de falso negativo o que a busca por
DOI confirma, porque aí a prova é o identificador. Similaridade alta de título
vira pedido de verificação, nunca veredito, e a tese ou o trabalho de conclusão
homônimo é apontado como tal — ele não cobre o artigo, e o registro segue ausente.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import glob
import json
import os
import time

from common import (
    ler_csv,
    escrever_csv,
    normalizar_doi,
    normalizar_titulo,
)

URL_BUSCA = "https://repositorio.ufrn.br/server/api/discover/search/objects"
PAUSA = 0.5  # cortesia com a API pública, como na coleta
TAMANHO = 20  # hits examinados por busca
SIM_VERIFICAR = 0.80  # abaixo do limiar M3 (0,95): candidato que merece olhar humano
TIPOS_ACADEMICOS = {"doctoralThesis", "masterThesis", "bachelorThesis"}

CAMPOS_SAIDA = [
    "estrato",
    "fonte",
    "id_base",
    "titulo_base",
    "ano_base",
    "url_base",
    "titulo_alvo",
    "ano_alvo",
    "url_alvo",
    "similaridade",
    "sugestao_triagem",
    "evidencia",
    "veredito_proposto",
    "origem_veredito",
    "veredito",
]


def _primeiro_autor(metadados: dict, campo: str) -> str:
    valores = metadados.get(campo) or []
    return (valores[0].get("value") or "").strip() if valores else ""


def indice_de_autores(dados: str) -> dict[str, str]:
    """source_id -> primeiro autor, lido das respostas brutas guardadas na coleta.

    O CSV consolidado não guarda autoria (o pareamento não a usa). A busca por autor
    precisa dela, e relê o `raw/` em vez de consultar as bases de novo.
    """
    autores: dict[str, str] = {}
    for caminho in glob.glob(os.path.join(dados, "raw", "scopus-*.json")):
        with open(caminho, encoding="utf-8") as fh:
            payload = json.load(fh)
        for entrada in payload.get("search-results", {}).get("entry", []) or []:
            eid = (entrada.get("eid") or "").strip()
            if eid:
                autores[eid] = (entrada.get("dc:creator") or "").strip()
    for caminho in glob.glob(os.path.join(dados, "raw", "wos-*.json")):
        with open(caminho, encoding="utf-8") as fh:
            payload = json.load(fh)
        for hit in payload.get("hits", []) or []:
            uid = (hit.get("uid") or "").strip()
            lista = ((hit.get("names") or {}).get("authors") or [])
            if uid and lista:
                autores[uid] = (lista[0].get("displayName") or "").strip()
    return autores


def buscar(termo: str) -> list[dict]:
    """Busca Discovery no repositório; devolve os itens achados, achatados."""
    from common import get_json

    if not termo.strip():
        return []
    payload = get_json(URL_BUSCA, {"query": termo, "size": TAMANHO, "dsoType": "item"})
    time.sleep(PAUSA)
    objetos = (
        payload.get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )
    itens = []
    for objeto in objetos:
        item = objeto.get("_embedded", {}).get("indexableObject", {}) or {}
        metadados = item.get("metadata", {}) or {}
        dois = []
        for campo, valores in metadados.items():
            if campo.startswith("dc.identifier"):
                for valor in valores:
                    doi = normalizar_doi(valor.get("value"))
                    if doi:
                        dois.append(doi)
        itens.append(
            {
                "titulo": _primeiro_autor(metadados, "dc.title"),
                "tipo": _primeiro_autor(metadados, "dc.type"),
                "ano": _primeiro_autor(metadados, "dc.date.issued")[:4],
                "handle": item.get("handle") or "",
                "dois": dois,
            }
        )
    return itens


def similaridade(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalizar_titulo(a), normalizar_titulo(b)).ratio()


def vizinho_local(titulo: str, repositorio: list[dict]) -> tuple[dict | None, float]:
    """Item do repositório com o título mais parecido, sem limiar. Só como evidência."""
    alvo = normalizar_titulo(titulo)
    fichas = set(alvo.split())
    melhor, melhor_sim = None, 0.0
    for item in repositorio:
        titulo_ri = normalizar_titulo(item["title"])
        # descarta o que não compartilha nenhuma palavra: SequenceMatcher em 54.450
        # títulos por registro custaria minutos sem mudar o resultado.
        if not fichas & set(titulo_ri.split()):
            continue
        sim = difflib.SequenceMatcher(None, alvo, titulo_ri).ratio()
        if sim > melhor_sim:
            melhor, melhor_sim = item, sim
    return melhor, melhor_sim


def url_handle(handle: str) -> str:
    return f"https://repositorio.ufrn.br/handle/{handle}" if handle else ""


def triar(registro: dict, autor: str, repositorio: list[dict]) -> dict:
    """Aplica as quatro buscas a um registro do estrato dos ausentes.

    A decisão não sai da similaridade de título sozinha. O trabalho depositado como
    tese ou trabalho de conclusão costuma trazer o título **traduzido** para o
    português, e a busca do repositório o encontra pelo resumo ou pelo título
    alternativo em inglês, com similaridade de título baixa. Por isso os achados são
    separados por classe: o item acadêmico não cobre o artigo, e o registro segue
    ausente; só o item não acadêmico é candidato a falso negativo.
    """
    doi = normalizar_doi(registro.get("url_base", "").replace("https://doi.org/", ""))
    titulo = registro["titulo_base"]
    notas: list[str] = []
    achado: dict | None = None
    sugestao = "ausência confirmada"

    if doi:
        hits = [i for i in buscar(f'"{doi}"') if doi in i["dois"]]
        if hits:
            achado = hits[0]
            sugestao = "FALSO NEGATIVO — o DOI existe no repositório; o par existia"
            notas.append(
                f"busca por DOI {doi}: achou [{achado['tipo']}] {achado['handle']}"
            )
        else:
            notas.append(f"busca por DOI {doi}: nenhum item")
    else:
        notas.append("registro da base sem DOI")

    if achado is None:
        candidatos: list[tuple[float, dict, str]] = []
        vistos: set[str] = set()
        # O título inteiro entre aspas é uma frase longa e falha por qualquer
        # divergência de pontuação; o trecho inicial recupera o mesmo trabalho
        # quando o título completo não retorna nada.
        palavras = titulo.split()
        trecho = " ".join(palavras[:8])
        buscas = [(f'"{titulo}"', "título")]
        if len(palavras) > 8:
            buscas.append((f'"{trecho}"', "início do título"))
        buscas.append((autor, "autor"))
        for termo, rotulo in buscas:
            if not termo.strip():
                continue
            hits = buscar(termo)
            notas.append(
                f"busca por {rotulo}{f' ({autor})' if rotulo == 'autor' else ''}: {len(hits)} item(ns)"
            )
            for item in hits:
                if item["handle"] in vistos:
                    continue
                vistos.add(item["handle"])
                candidatos.append((similaridade(titulo, item["titulo"]), item, rotulo))

        academicos = sorted(
            (c for c in candidatos if c[1]["tipo"] in TIPOS_ACADEMICOS), key=lambda t: -t[0]
        )
        outros = sorted(
            (c for c in candidatos if c[1]["tipo"] not in TIPOS_ACADEMICOS), key=lambda t: -t[0]
        )

        # Derivação não se decide por similaridade. O trabalho de conclusão que dá
        # origem ao artigo costuma estar depositado com o título vertido para o
        # português, e a similaridade entre o título em inglês e o título em
        # português fica na casa de 0,3 a 0,5 — abaixo de qualquer limiar defensável,
        # e no mesmo patamar de duas teses sem relação nenhuma. O script lista a
        # tese e diz de onde ela veio; quem decide é o conferente, lendo os dois
        # títulos. Seja qual for a decisão, o registro **segue ausente**: a tese não
        # é candidato. A derivação importa ao mecanismo descrito no artigo, não à
        # medida de cobertura. O falso negativo, esse sim, só pode vir de item não
        # acadêmico, e é o único caso em que o script pede revisão do pareamento.
        if outros and outros[0][0] >= SIM_VERIFICAR:
            sim, item, rotulo = outros[0]
            achado = item
            sugestao = (
                "VERIFICAR — possível falso negativo: item não acadêmico de título "
                "próximo, abaixo do limiar M3"
            )
        elif academicos:
            achado = academicos[0][1]
            sugestao = (
                "ausência confirmada — o artigo não está no RI; há tese/TCC do autor, "
                "conferir se é a derivada (o título traduzido não bate por similaridade)"
            )

        for rotulo_bloco, bloco in (
            ("tese/TCC", academicos),
            ("itens não acadêmicos", outros),
        ):
            for sim, item, origem in bloco[:3]:
                notas.append(
                    f"{rotulo_bloco} (achada por {origem}): [{item['tipo']}] "
                    f"{item['titulo'][:60]!r} ({item['ano']}), sim {sim:.2f}, "
                    f"{item['handle']}"
                )
        if not candidatos:
            notas.append("busca por título e por autor: nenhum item no repositório")

    item_local, sim_local = vizinho_local(titulo, repositorio)
    if item_local:
        notas.append(
            f"vizinho mais próximo no RI local: [{item_local['type']}] "
            f"{item_local['title'][:60]!r}, similaridade {sim_local:.2f}"
        )

    return {
        **{c: registro.get(c, "") for c in CAMPOS_SAIDA if c in registro},
        "titulo_alvo": achado["titulo"] if achado else "",
        "ano_alvo": achado["ano"] if achado else "",
        "url_alvo": url_handle(achado["handle"]) if achado else "",
        "similaridade": "",
        "sugestao_triagem": sugestao,
        "evidencia": "; ".join(notas),
        "veredito_proposto": sugestao,
        "origem_veredito": "",
        "veredito": "",
    }


def _par(linha: dict) -> tuple[str, str, str]:
    """Identidade do par conferido: registro da base × item do repositório."""
    url = linha.get("url_alvo", "")
    handle = url.rsplit("/handle/", 1)[-1] if "/handle/" in url else ""
    return (linha["fonte"], linha["id_base"], handle)


def executar(dados: str) -> None:
    amostra = ler_csv(os.path.join(dados, "validacao-manual.csv"))
    anterior = {
        (l["fonte"], l["id_base"], l["url_alvo"]): l
        for l in ler_csv(os.path.join(dados, "triagem-assistida.csv"))
    }
    # Vereditos que o autor já deu no 1º turno. Parte dos pares sorteados agora é a
    # mesma de então — item idêntico, pergunta idêntica, decisão já tomada. O
    # veredito é transportado com a origem registrada, e não pedido de novo; o que
    # nunca foi julgado continua em branco.
    julgados = {
        _par(l): l["veredito"]
        for l in ler_csv(os.path.join(dados, "validacao-manual-r1.csv"))
        if l["veredito"].strip()
    }
    repositorio = ler_csv(os.path.join(dados, "ri-todos.csv"))
    autores = indice_de_autores(dados)
    print(f"amostra: {len(amostra)} linhas; repositório: {len(repositorio)} itens")

    saida: list[dict] = []
    pendentes = [l for l in amostra if l["estrato"] == "ausente"]
    print(f"triagem a fazer: {len(pendentes)} do estrato dos ausentes")

    for linha in amostra:
        chave = (linha["fonte"], linha["id_base"], linha["url_alvo"])
        if chave in anterior:  # estratos já triados: aproveita a evidência escrita
            velha = anterior[chave]
            ficha = {
                **{c: linha.get(c, "") for c in CAMPOS_SAIDA if c in linha},
                "sugestao_triagem": velha["sugestao_triagem"],
                "evidencia": velha["evidencia"],
                "veredito_proposto": velha["sugestao_triagem"],
                "origem_veredito": "",
                "veredito": "",
            }
        else:
            autor = autores.get(linha["id_base"], "")
            ficha = triar(linha, autor, repositorio)
            print(f"  [{len(saida) + 1:3d}/{len(amostra)}] {ficha['sugestao_triagem'][:48]}")

        veredito = julgados.get(_par(ficha))
        if veredito:
            ficha["veredito"] = veredito
            ficha["origem_veredito"] = "1º turno, conferido pelo autor (validacao-manual-r1.csv)"
        saida.append(ficha)

    caminho = os.path.join(dados, "validacao-manual.csv")
    escrever_csv(caminho, saida, CAMPOS_SAIDA)
    contagem = collections.Counter(l["veredito_proposto"].split("—")[0].strip() for l in saida)
    print(f"\ngravado: {caminho}")
    for chave, n in contagem.most_common():
        print(f"  {n:3d}  {chave}")
    transportados = sum(1 for l in saida if l["origem_veredito"])
    falta = sum(1 for l in saida if not l["veredito"].strip())
    print(f"\nveredito transportado do 1º turno: {transportados}")
    print(f"veredito a preencher à mão: {falta}")
    print("A coluna 'veredito_proposto' é sugestão da triagem, não decisão.")


def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", required=True, help="diretório dos CSVs")
    executar(parser.parse_args().dados)


if __name__ == "__main__":
    principal()
