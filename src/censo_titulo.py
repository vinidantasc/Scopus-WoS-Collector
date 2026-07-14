"""Censo do estrato pareado por título (etapas M2 e M3).

    python3 src/censo_titulo.py --dados /caminho/dados

Emite a evidência da conferência do estrato por título, um par por linha, com o DOI dos
dois lados e o diagnóstico da divergência entre eles. É o estrato que os dois turnos de
conferência não examinaram, e o único em que o pareamento não tem prova de identidade:
o título casa, mas o título é compartilhado por trabalhos distintos.

O diagnóstico do DOI **não decide** o veredito, apenas o instrui. A divergência entre os
dois DOI tem duas causas opostas, e só a leitura de cada par separa uma da outra:

- o repositório depositou o DOI **corrompido** — truncado no prefixo do editor, sem o
  hífen, com o espaço escapado, ou tomado de outro artigo. O par é legítimo: o artigo
  está lá, o identificador é que está errado. É a causa da maioria.
- os dois lados são **trabalhos diferentes de mesmo título** — a revisão sistemática e o
  artigo de periódico que a resume, por exemplo. O par é falso, e o registro da base
  volta a ser ausência, pelo ``falsos-positivos-conferencia.csv``.

Por isso a divergência de DOI não vira regra automática de rejeição: descartaria o par
verdadeiro junto com o falso, e o faria na direção da hipótese do estudo.

Somente biblioteca padrão.
"""

from __future__ import annotations

import argparse
import os
import re

from common import escrever_csv, ler_csv

CAMPOS = [
    "fonte",
    "etapa",
    "id_base",
    "handle",
    "similaridade",
    "titulo_base",
    "titulo_ri",
    "ano_base",
    "ano_ri",
    "doi_base",
    "doi_ri",
    "diagnostico_doi",
    "veredito",
    "origem_veredito",
]

ORIGEM = "censo do estrato por título em 14/07/2026; DOI de cada lado resolvidos no Crossref; confirmado pelo autor"


def _limpo(doi: str) -> str:
    """Reduz o DOI à sua forma comparável: só letras e dígitos, sem escape de espaço."""
    return re.sub(r"[^a-z0-9]", "", doi.lower().replace("%20", ""))


def diagnosticar(doi_base: str, doi_ri: str) -> str:
    """Por que os dois DOI divergem — ou por que a divergência não existe."""
    if not doi_base or not doi_ri:
        return "um lado sem DOI: o pareamento por título é a única via"
    a, b = _limpo(doi_base), _limpo(doi_ri)
    if a == b:
        return "mesmo DOI, divergência só de pontuação no depósito"
    if a.startswith(b) or b.startswith(a):
        return "mesmo DOI, truncado no depósito do repositório"
    if "arxiv" in a or "arxiv" in b:
        return "um lado traz o DOI do preprint, o outro o da versão publicada"
    return "DOI irreconciliáveis: conferir se são dois trabalhos ou se o repositório depositou o DOI de outro artigo"


def executar(dados: str) -> None:
    ri = {r["source_id"]: r for r in ler_csv(os.path.join(dados, "ri-todos.csv"))}
    falsos = {
        (l["fonte"], l["id_base"])
        for l in ler_csv(os.path.join(dados, "falsos-positivos-conferencia.csv"))
    }

    linhas = []
    for fonte in ("scopus", "wos"):
        for par in ler_csv(os.path.join(dados, f"match-{fonte}-ri.csv")):
            if par["etapa"] not in ("M2", "M3"):
                continue
            alvo = ri[par["id_alvo"]]
            linhas.append(
                {
                    "fonte": fonte,
                    "etapa": par["etapa"],
                    "id_base": par["id_base"],
                    "handle": alvo.get("handle", ""),
                    "similaridade": par["similaridade"],
                    "titulo_base": par["titulo_base"],
                    "titulo_ri": alvo["title"],
                    "ano_base": par["ano_base"],
                    "ano_ri": alvo["year"],
                    "doi_base": par["doi"],
                    "doi_ri": alvo["doi"],
                    "diagnostico_doi": diagnosticar(par["doi"], alvo["doi"]),
                    "veredito": "par correto",
                    "origem_veredito": ORIGEM,
                }
            )

    # o par reprovado já saiu dos pares na etapa F; entra aqui pelo registro da reprovação,
    # para que o censo do estrato fique completo no arquivo, e não só o que sobreviveu a ele
    for l in ler_csv(os.path.join(dados, "falsos-positivos-conferencia.csv")):
        linhas.append(
            {
                "fonte": l["fonte"],
                "etapa": "M2",
                "id_base": l["id_base"],
                "handle": l["handle"],
                "similaridade": "1.0000",
                "titulo_base": l["titulo"],
                "titulo_ri": ri_titulo(ri, l["handle"]),
                "ano_base": "",
                "ano_ri": "",
                "doi_base": l["doi_base"],
                "doi_ri": l["doi_ri"],
                "diagnostico_doi": diagnosticar(l["doi_base"], l["doi_ri"]),
                "veredito": "FALSO POSITIVO — dois trabalhos de mesmo título; o do repositório não é o da base (etapa F)",
                "origem_veredito": l.get("origem_veredito", ORIGEM),
            }
        )

    caminho = os.path.join(dados, "censo-titulo.csv")
    escrever_csv(caminho, linhas, CAMPOS)
    corretos = sum(1 for l in linhas if l["veredito"] == "par correto")
    print(f"censo do estrato por título: {len(linhas)} pares, {corretos} corretos, {len(falsos)} reprovados")


def ri_titulo(ri: dict, handle: str) -> str:
    for r in ri.values():
        if r.get("handle") == handle:
            return r["title"]
    return ""


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com os CSVs consolidados")
    a = p.parse_args()
    executar(a.dados)
