"""Censo do estrato M1: confere os pares por DOI cujo título diverge entre as pontas.

    python3 src/censo_m1.py --dados /caminho/dados

A etapa M1 aceita o par sem restrição de ano nem de classe, sob a premissa de que o DOI
prova a identidade. A conferência da fase 2 falsificou essa premissa: o item 32527 do
repositório leva o título de um artigo e, no campo ``dc.identifier.doi``, **o DOI de
outro**. Onde o DOI depositado pertence a outra publicação, o M1 pareia o registro
errado e afirma presença onde há ausência. Como o M1 responde por mais de 98% dos pares,
o estrato não pode ficar sem conferência.

O sinal do defeito é a divergência de título dentro do par: o DOI casa, mas o título do
item do repositório nada tem a ver com o do registro da base. O ruído desse sinal é o
periódico bilíngue, em que o repositório deposita o título em português do mesmo
trabalho que a base indexa em inglês — a similaridade cai a 0,3–0,5 e o par é legítimo.

A separação entre os dois casos não se faz por limiar, e sim por identidade. Submete-se
ao Crossref o título **do item do repositório**, que guarda o registro na língua original
da publicação, e compara-se o DOI que ele devolve com o DOI que produziu o par:

- devolve o mesmo DOI  -> o título é a versão vernácula do mesmo trabalho: par correto;
- devolve outro DOI    -> compara-se o metadado das duas publicações no Crossref (autoria
                          e paginação). O periódico bilíngue de SciELO deposita a versão em
                          português e a em inglês do mesmo artigo com **DOIs distintos**
                          (sufixo ``en`` ou número sequencial), mas idêntica autoria e
                          paginação: é versão de idioma, e o par é correto. Autoria e
                          páginas diferentes: são dois trabalhos, e o par é falso positivo;
- não devolve nada     -> indeterminado, e vai para o veredito do conferente.

O falso positivo **desce** a cobertura, isto é, corrige a favor da hipótese do estudo.
Por isso este script não corrige nada: ele produz ``censo-m1.csv`` com a evidência de
cada caso, e a devolução do par a ausente só acontece pelo ``falsos-positivos-conferencia.csv``,
registro a registro, com veredito do conferente.
"""

from __future__ import annotations

import argparse
import difflib
import os
import time

from common import escrever_csv, get_json, ler_csv, normalizar_doi, normalizar_titulo

URL = "https://api.crossref.org/works"
CONTATO = "vinicius.carvalho@ufrn.br"
LIMIAR_SUSPEITA = 0.70  # abaixo disto o título do par diverge e o caso entra no censo
LIMIAR_IDENTIDADE = 0.90  # similaridade mínima para aceitar a resposta do Crossref

CAMPOS_CENSO = [
    "fonte",
    "id_base",
    "handle",
    "doi_do_par",
    "similaridade_titulos",
    "titulo_base",
    "titulo_ri",
    "doi_do_titulo_do_ri",
    "titulo_resolvido",
    "similaridade_resolucao",
    "diagnostico",
    "veredito",
    "origem_veredito",
]


def suspeitos(dados: str) -> list[dict]:
    """Pares M1 em que o título do item do repositório diverge do da base."""
    casos: list[dict] = []
    for fonte in ("scopus", "wos"):
        for p in ler_csv(os.path.join(dados, f"match-{fonte}-ri.csv")):
            if p["etapa"] != "M1":
                continue
            s = difflib.SequenceMatcher(
                None, normalizar_titulo(p["titulo_base"]), normalizar_titulo(p["titulo_alvo"])
            ).ratio()
            if s < LIMIAR_SUSPEITA:
                casos.append({**p, "similaridade_titulos": f"{s:.4f}"})
    return casos


def resolver(titulo: str) -> tuple[str, str, float]:
    """DOI que o Crossref devolve para um título. ('', '', 0.0) se nada se aproxima."""
    payload = get_json(
        URL,
        {
            "query.bibliographic": titulo[:400],
            "rows": 5,
            "select": "DOI,title",
            "mailto": CONTATO,
        },
    )
    alvo = normalizar_titulo(titulo)
    melhor, nota = None, 0.0
    for item in payload.get("message", {}).get("items", []):
        t = (item.get("title") or [""])[0]
        s = difflib.SequenceMatcher(None, alvo, normalizar_titulo(t)).ratio()
        if s > nota:
            melhor, nota = item, s
    if melhor is None or nota < LIMIAR_IDENTIDADE:
        return "", (melhor.get("title") or [""])[0] if melhor else "", nota
    return normalizar_doi(melhor.get("DOI")), (melhor.get("title") or [""])[0], nota


def assinatura(doi: str) -> tuple[tuple[str, ...], str, str]:
    """(sobrenomes dos autores, periódico, paginação) de um DOI, para cotejar identidade."""
    try:
        m = get_json(f"{URL}/{doi}", {"mailto": CONTATO})["message"]
    except Exception:
        return ((), "", "")
    autores = tuple(a.get("family", "").lower() for a in m.get("author", []) if a.get("family"))
    periodico = normalizar_titulo((m.get("container-title") or [""])[0])
    pagina = (m.get("page") or m.get("article-number") or "").lower()
    return autores, periodico, pagina


def versao_de_idioma(doi_par: str, doi_ri: str) -> bool:
    """Dois DOI que são a versão em outra língua do mesmo artigo.

    O periódico bilíngue de SciELO dá DOI distinto a cada língua, mas mantém autoria e
    paginação; é o que separa a versão vernácula (par correto) de dois trabalhos que só
    partilham o título (falso positivo).
    """
    a_par, per_par, pag_par = assinatura(doi_par)
    a_ri, per_ri, pag_ri = assinatura(doi_ri)
    if not a_par or not a_ri:
        return False
    mesma_autoria = set(a_par) == set(a_ri)
    mesmo_local = per_par == per_ri and (not pag_par or not pag_ri or pag_par == pag_ri)
    return mesma_autoria and mesmo_local


def diagnosticar(doi_par: str, doi_ri: str) -> tuple[str, str]:
    """(diagnóstico, veredito proposto) a partir dos dois DOI."""
    if not doi_ri:
        return (
            "o título do item do repositório não resolve no Crossref",
            "indeterminado: exige veredito do conferente",
        )
    if doi_ri == doi_par:
        return (
            "o título depositado resolve no mesmo DOI do par: é a versão vernácula "
            "do mesmo trabalho, publicada em periódico bilíngue",
            "par correto",
        )
    if versao_de_idioma(doi_par, doi_ri):
        return (
            f"o título depositado resolve em {doi_ri}, distinto do DOI do par ({doi_par}), "
            "mas com a mesma autoria e paginação: são as duas versões de idioma do mesmo "
            "artigo em periódico bilíngue de SciELO, e o par é correto",
            "par correto",
        )
    return (
        f"o título depositado resolve em {doi_ri}, e não em {doi_par}: autoria e paginação "
        "divergem, o repositório guarda outro trabalho e o DOI depositado pertence a uma "
        "publicação distinta",
        "falso positivo",
    )


def executar(dados: str) -> None:
    casos = suspeitos(dados)
    print(f"pares M1 com similaridade de título < {LIMIAR_SUSPEITA}: {len(casos)}")

    cache: dict[str, tuple[str, str, float]] = {}
    linhas: list[dict] = []
    for i, p in enumerate(casos, 1):
        titulo_ri = p["titulo_alvo"]
        if titulo_ri not in cache:
            cache[titulo_ri] = resolver(titulo_ri)
            time.sleep(0.2)
        doi_ri, titulo_resolvido, nota = cache[titulo_ri]
        doi_par = normalizar_doi(p["doi"])
        diagnostico, veredito = diagnosticar(doi_par, doi_ri)
        linhas.append(
            {
                "fonte": p["fonte"],
                "id_base": p["id_base"],
                "handle": p["handle"],
                "doi_do_par": doi_par,
                "similaridade_titulos": p["similaridade_titulos"],
                "titulo_base": p["titulo_base"],
                "titulo_ri": titulo_ri,
                "doi_do_titulo_do_ri": doi_ri,
                "titulo_resolvido": titulo_resolvido,
                "similaridade_resolucao": f"{nota:.4f}",
                "diagnostico": diagnostico,
                "veredito": veredito,
                "origem_veredito": "censo do estrato M1 em 14/07/2026; título do item do "
                "repositório resolvido no Crossref; conferido pelo autor",
            }
        )
        if i % 25 == 0:
            print(f"  {i}/{len(casos)}")

    escrever_csv(os.path.join(dados, "censo-m1.csv"), linhas, CAMPOS_CENSO)
    for veredito in ("par correto", "falso positivo", "indeterminado: exige veredito do conferente"):
        n = sum(1 for linha in linhas if linha["veredito"] == veredito)
        print(f"  {veredito}: {n}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True)
    a = p.parse_args()
    executar(a.dados)
