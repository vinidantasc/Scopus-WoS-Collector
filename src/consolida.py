"""Consolida as fatias anuais, remove duplicatas e conta o que a metodologia precisa declarar.

    python3 src/consolida.py --dados /caminho/dados --de 2020 --ate 2025

Produz scopus-all.csv e wos-all.csv a partir das fatias anuais, deduplicando por
DOI dentro de cada fonte (a Scopus ocasionalmente devolve o mesmo trabalho como
artigo e como conference paper, e o repositório tem depósitos repetidos), e
imprime, em Markdown, os números que entram em dados/COLETA.md e na seção de
metodologia do artigo: total por fonte e ano, registros sem DOI e duplicatas
removidas.
"""

from __future__ import annotations

import argparse
import collections
import os

from common import CAMPOS, CAMPOS_RI, escrever_csv, ler_csv


def deduplicar(registros: list[dict]) -> tuple[list[dict], int, int]:
    """Remove repetição de identificador e de DOI. Devolve (limpos, dup_id, dup_doi)."""
    vistos_id: set[str] = set()
    vistos_doi: set[str] = set()
    limpos: list[dict] = []
    dup_id = dup_doi = 0
    for r in registros:
        if r["source_id"] in vistos_id:
            dup_id += 1
            continue
        if r["doi"] and r["doi"] in vistos_doi:
            dup_doi += 1
            continue
        vistos_id.add(r["source_id"])
        if r["doi"]:
            vistos_doi.add(r["doi"])
        limpos.append(r)
    return limpos, dup_id, dup_doi


def consolidar(fonte: str, dados: str, de: int, ate: int) -> dict | None:
    """Junta as fatias anuais de uma fonte, deduplica e grava <fonte>-all.csv."""
    campos = CAMPOS_RI if fonte == "ri" else CAMPOS
    registros: list[dict] = []
    for ano in range(de, ate + 1):
        caminho = os.path.join(dados, f"{fonte}-{ano}.csv")
        if not os.path.exists(caminho):
            print(f"  ausente: {caminho}")
            continue
        registros.extend(ler_csv(caminho))
    if not registros:
        return None

    limpos, dup_id, dup_doi = deduplicar(registros)
    dentro, fora = recortar(limpos, de, ate)
    escrever_csv(os.path.join(dados, f"{fonte}-all.csv"), dentro, campos)
    return {
        "fonte": fonte,
        "por_ano": collections.Counter(int(r["year"]) for r in dentro),
        "bruto": len(registros),
        "final": len(dentro),
        "dup_id": dup_id,
        "dup_doi": dup_doi,
        "fora": collections.Counter(r["year"] for r in fora),
        "sem_doi": sum(1 for r in dentro if not r["doi"]),
        "tipos": collections.Counter(r["type"] for r in dentro),
    }


def recortar(registros: list[dict], de: int, ate: int) -> tuple[list[dict], list[dict]]:
    """Separa o que está no recorte temporal do que caiu fora dele.

    O ano de um registro é o do seu próprio campo, nunca o da fatia em que foi
    baixado. A distinção importa porque a fatia PY=2025 da Web of Science também
    devolve o trabalho cujo fascículo é de 2026 e que só teve publicação antecipada
    em 2025. Esses registros estão fora do universo do estudo, que é a produção com
    ano de publicação entre 2020 e 2025 nas bases.
    """
    dentro, fora = [], []
    for r in registros:
        ano = int(r["year"]) if r["year"].isdigit() else 0
        (dentro if de <= ano <= ate else fora).append(r)
    return dentro, fora


def relatar(resumos: list[dict], de: int, ate: int) -> None:
    anos = list(range(de, ate + 1))
    print("\n## Registros por fonte e ano (ano do próprio registro, após deduplicação)\n")
    cabecalho = " | ".join(str(a) for a in anos)
    print(f"| fonte | {cabecalho} | total no recorte |")
    print("|---" * (len(anos) + 2) + "|")
    for r in resumos:
        celulas = " | ".join(str(r["por_ano"].get(a, 0)) for a in anos)
        print(f"| {r['fonte']} | {celulas} | {r['final']} |")

    print("\n## Depuração do bruto ao universo do estudo\n")
    print("| fonte | bruto (soma das fatias) | dup. por identificador | dup. por DOI | fora do recorte | universo |")
    print("|---|---|---|---|---|---|")
    for r in resumos:
        fora = sum(r["fora"].values())
        detalhe = f"{fora}" + (f" ({', '.join(sorted(r['fora']))})" if fora else "")
        print(f"| {r['fonte']} | {r['bruto']} | {r['dup_id']} | {r['dup_doi']} | {detalhe} | {r['final']} |")

    print("\n## Registros sem DOI\n")
    print("| fonte | sem DOI | % do universo |")
    print("|---|---|---|")
    for r in resumos:
        pct = 100 * r["sem_doi"] / r["final"] if r["final"] else 0
        print(f"| {r['fonte']} | {r['sem_doi']} | {pct:.1f}% |")

    for r in resumos:
        print(f"\n## Tipos de documento — {r['fonte']}\n")
        print("| tipo | n |")
        print("|---|---|")
        for tipo, n in r["tipos"].most_common(12):
            print(f"| {tipo or '(vazio)'} | {n} |")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com os CSVs das fatias")
    p.add_argument("--de", type=int, default=2020)
    p.add_argument("--ate", type=int, default=2025)
    a = p.parse_args()

    resumos = [r for r in (consolidar(f, a.dados, a.de, a.ate) for f in ("scopus", "wos", "ri")) if r]
    relatar(resumos, a.de, a.ate)
