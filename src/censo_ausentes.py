"""Censo do falso negativo: recupera no Crossref o DOI dos candidatos que o repositório
depositou sem identificador.

    python3 src/censo_ausentes.py --dados /caminho/dados

O falso negativo do pareamento só pode existir num lugar. Onde o registro da base tem
DOI e o item do repositório também, a decisão é por identidade, e a etapa M1 é exaustiva.
O par escapa quando o item **está** no repositório mas foi depositado **sem DOI
recuperável** em nenhum campo ``dc.identifier.*``, e o título diverge do da base a ponto
de as etapas por título não o alcançarem — o que é a regra, e não a exceção, quando o
título foi vertido para o português (a similaridade contra o título em inglês fica entre
0,3 e 0,5, o mesmo patamar de dois trabalhos sem relação nenhuma).

Enquanto essa taxa era estimada por amostra, o teto do intervalo de confiança incidia
sobre todo o conjunto dos ausentes, e era largo. Este script troca a amostra pelo censo:
percorre **todos** os candidatos sem DOI, submete o título ao Crossref, que guarda o
registro na língua original da publicação, e devolve o DOI que o depósito não trouxe.
O cruzamento desse DOI com o conjunto dos ausentes (feito no ``matching.py``, etapa R)
mede o falso negativo por identidade, e não mais por amostragem.

A execução é resumível: o que já está no CSV de saída não é consultado de novo.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import os
import time
import urllib.parse

from common import ano_de, escrever_csv, get_json, ler_csv, normalizar_doi, normalizar_titulo

URL = "https://api.crossref.org/works"
CONTATO = "vinicius.carvalho@ufrn.br"  # entra no pool cortês do Crossref
TESES_RI = {"bachelorThesis", "masterThesis", "doctoralThesis", "postGraduateThesis"}
LIMIAR = 0.90  # similaridade mínima entre o título depositado e o título do Crossref
TOLERANCIA_ANO = 2  # o ano do depósito diverge do da publicação com frequência
CANDIDATOS_CROSSREF = 5  # respostas examinadas por consulta

CAMPOS_CENSO = [
    "handle",
    "titulo_ri",
    "ano_ri",
    "tipo_ri",
    "doi_recuperado",
    "titulo_crossref",
    "ano_crossref",
    "similaridade",
    "veredito",
]


def alvos(dados: str, feitos: set[str]) -> list[dict]:
    """Candidatos do pareamento que o repositório depositou sem DOI algum."""
    ri = ler_csv(os.path.join(dados, "ri-todos.csv"))
    return [
        r
        for r in ri
        if r["type"] not in TESES_RI
        and not r["doi"]
        and r["title"].strip()
        and r["handle"] not in feitos
    ]


def consultar(titulo: str) -> list[dict]:
    params = {
        "query.bibliographic": titulo[:400],
        "rows": CANDIDATOS_CROSSREF,
        "select": "DOI,title,issued",
        "mailto": CONTATO,
    }
    payload = get_json(URL, params)
    return payload.get("message", {}).get("items", [])


def ano_crossref(item: dict) -> int:
    partes = (item.get("issued") or {}).get("date-parts") or [[]]
    return partes[0][0] if partes and partes[0] else 0


def melhor(item_ri: dict, respostas: list[dict]) -> tuple[dict | None, float]:
    """Resposta do Crossref cujo título mais se aproxima do título depositado."""
    alvo = normalizar_titulo(item_ri["title"])
    escolhido, nota = None, 0.0
    for item in respostas:
        titulos = item.get("title") or [""]
        s = difflib.SequenceMatcher(None, alvo, normalizar_titulo(titulos[0])).ratio()
        if s > nota:
            escolhido, nota = item, s
    return escolhido, nota


def aceitar(item_ri: dict, item: dict | None, nota: float) -> bool:
    """Aceita o DOI recuperado quando título e ano sustentam a identidade.

    O limiar é alto de propósito. Este censo pode **subir** a cobertura, isto é,
    corrige contra a hipótese do estudo; ainda assim, um DOI atribuído por engano
    criaria par onde não há, e o par falso é o erro que nenhuma direção justifica.
    """
    if item is None or nota < LIMIAR:
        return False
    a_ri, a_cr = ano_de(item_ri), ano_crossref(item)
    return not (a_ri and a_cr) or abs(a_ri - a_cr) <= TOLERANCIA_ANO


def executar(dados: str) -> None:
    saida = os.path.join(dados, "censo-ausentes.csv")
    feitos: set[str] = set()
    linhas: list[dict] = []
    if os.path.exists(saida):
        linhas = ler_csv(saida)
        feitos = {linha["handle"] for linha in linhas}
        print(f"retomando: {len(feitos)} candidatos já consultados")

    pendentes = alvos(dados, feitos)
    print(f"candidatos sem DOI a consultar no Crossref: {len(pendentes)}")

    for i, item_ri in enumerate(pendentes, 1):
        try:
            respostas = consultar(item_ri["title"])
        except Exception as erro:  # rede: registra e segue; a execução é resumível
            print(f"  {item_ri['handle']}: falha ({erro})")
            continue
        item, nota = melhor(item_ri, respostas)
        ok = aceitar(item_ri, item, nota)
        linhas.append(
            {
                "handle": item_ri["handle"],
                "titulo_ri": item_ri["title"],
                "ano_ri": item_ri["year"],
                "tipo_ri": item_ri["type"],
                "doi_recuperado": normalizar_doi(item.get("DOI")) if ok else "",
                "titulo_crossref": (item.get("title") or [""])[0] if item else "",
                "ano_crossref": ano_crossref(item) if item else "",
                "similaridade": f"{nota:.4f}",
                "veredito": "DOI recuperado" if ok else "sem correspondência no Crossref",
            }
        )
        if i % 50 == 0:
            escrever_csv(saida, linhas, CAMPOS_CENSO)
            achados = sum(1 for linha in linhas if linha["doi_recuperado"])
            print(f"  {i}/{len(pendentes)} | DOI recuperado até aqui: {achados}")
        time.sleep(0.2)

    escrever_csv(saida, linhas, CAMPOS_CENSO)
    achados = sum(1 for linha in linhas if linha["doi_recuperado"])
    print(f"censo concluído: {achados} DOI recuperados em {len(linhas)} candidatos sem DOI")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True)
    a = p.parse_args()
    executar(a.dados)
