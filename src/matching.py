"""Fase 2 — pareamento dos registros das bases com os itens do repositório.

    python3 src/matching.py --dados /caminho/dados

Para cada registro da Scopus e da Web of Science publicado no recorte do estudo,
decide se existe item correspondente no Repositório Institucional. O que não parear
é a defasagem de cobertura, objeto do artigo. O mesmo procedimento pareia Scopus
com Web of Science, para medir a sobreposição entre as bases.

O pareamento é local, sobre os CSVs da fase 1, e não por consulta ao repositório
registro a registro: a busca remota multiplicaria as requisições e teria erro
próprio, do motor de indexação, sobreposto ao erro que se quer medir.

Universo e candidatos são coisas distintas. O universo medido é o das bases no
recorte 2020–2025. Os candidatos são todos os itens do repositório, de qualquer ano
(``ri-todos.csv``), porque o artigo publicado em 2020 e depositado com data
divergente está no repositório e contá-lo como ausente superestimaria a defasagem.

Três etapas, aplicadas em ordem; o registro sai na primeira que casar:

    M1  DOI normalizado igual                             — sem restrição de ano
    M2  título normalizado igual e |Δano| ≤ 1
    M3  título com similaridade ≥ 0,95 e |Δano| ≤ 1       — conferência manual

A tolerância de um ano acomoda a divergência entre a data de publicação antecipada,
que as bases registram, e a data do fascículo, que o repositório costuma depositar.
No M1 não há restrição de ano: um DOI encontrado prova que o item está lá.

O M3 não compara todos os pares possíveis, que seriam centenas de milhões. Um índice
invertido de tokens do título restringe a comparação aos itens do repositório que
compartilham ao menos um token discriminante com o registro da base. A restrição não
descarta par legítimo: dois títulos com similaridade de 0,95 ou mais são quase
idênticos e necessariamente compartilham tokens.

Somente biblioteca padrão.
"""

from __future__ import annotations

import argparse
import collections
import csv
import difflib
import os
import random

from common import CAMPOS, ano_de, escrever_csv, ler_csv, normalizar_titulo

LIMIAR_M3 = 0.95  # similaridade mínima aceita na etapa fuzzy
TOLERANCIA_ANO = 1  # |Δano| aceito nas etapas por título
TAMANHO_MINIMO_TOKEN = 4  # token curto não discrimina ("de", "the", "uma")
FREQUENCIA_MAXIMA_TOKEN = 0.01  # token presente em >1% dos candidatos é ruído
CANDIDATOS_POR_REGISTRO = 20  # avaliados por similaridade, os de maior sobreposição
SEMENTE = 20260713  # amostras de conferência reproduzíveis
TAMANHO_AMOSTRA = 50  # por estrato, conforme 02-metodologia-matching.md §3

CAMPOS_PAR = [
    "fonte",
    "id_base",
    "id_alvo",
    "handle",
    "etapa",
    "similaridade",
    "titulo_base",
    "titulo_alvo",
    "ano_base",
    "ano_alvo",
    "tipo_alvo",
    "doi",
]
CAMPOS_VALIDACAO = [
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
    "veredito",
]


class Indice:
    """Índice dos candidatos: por DOI, por título e por token do título."""

    def __init__(self, registros: list[dict]) -> None:
        self.registros = registros
        self.por_doi: dict[str, int] = {}
        self.por_titulo: dict[str, list[int]] = collections.defaultdict(list)
        self.por_token: dict[str, list[int]] = collections.defaultdict(list)
        self.titulos: list[str] = []
        self.anos: list[int] = []

        for i, r in enumerate(registros):
            titulo = normalizar_titulo(r["title"])
            self.titulos.append(titulo)
            self.anos.append(ano_de(r))
            # o primeiro depósito vence: repetição de DOI no repositório é depósito
            # duplicado do mesmo trabalho, e qualquer um dos dois prova a presença
            if r["doi"]:
                self.por_doi.setdefault(r["doi"], i)
            if titulo:
                self.por_titulo[titulo].append(i)
                for token in set(titulo.split()):
                    if len(token) >= TAMANHO_MINIMO_TOKEN:
                        self.por_token[token].append(i)

        teto = max(1, int(FREQUENCIA_MAXIMA_TOKEN * len(registros)))
        self.tokens_frequentes = {t for t, ids in self.por_token.items() if len(ids) > teto}

    def compativel(self, i: int, ano_base: int) -> bool:
        """Anos compatíveis dentro da tolerância; ano ausente não desqualifica."""
        ano = self.anos[i]
        return ano == 0 or ano_base == 0 or abs(ano - ano_base) <= TOLERANCIA_ANO

    def candidatos(self, titulo: str) -> list[int]:
        """Itens que compartilham token discriminante, os de maior sobreposição antes."""
        tokens = {t for t in titulo.split() if len(t) >= TAMANHO_MINIMO_TOKEN}
        discriminantes = tokens - self.tokens_frequentes
        # título feito só de termos frequentes ("estudo de caso") não tem token raro;
        # nesse caso vale mais comparar contra os candidatos comuns do que desistir
        contagem: collections.Counter[int] = collections.Counter()
        for token in discriminantes or tokens:
            contagem.update(self.por_token.get(token, ()))
        return [i for i, _ in contagem.most_common(CANDIDATOS_POR_REGISTRO)]


def parear(base: list[dict], indice: Indice, fonte: str) -> tuple[list[dict], list[dict]]:
    """Aplica M1, M2 e M3 sobre os registros da base. Devolve (pares, ausentes)."""
    pares: list[dict] = []
    ausentes: list[dict] = []

    for registro in base:
        titulo = normalizar_titulo(registro["title"])
        ano = ano_de(registro)
        achado = None

        if registro["doi"] and registro["doi"] in indice.por_doi:
            achado = (indice.por_doi[registro["doi"]], "M1", 1.0)

        if achado is None and titulo:
            for i in indice.por_titulo.get(titulo, ()):
                if indice.compativel(i, ano):
                    achado = (i, "M2", 1.0)
                    break

        if achado is None and titulo:
            melhor, similaridade_melhor = None, 0.0
            for i in indice.candidatos(titulo):
                if not indice.compativel(i, ano):
                    continue
                similaridade = difflib.SequenceMatcher(None, titulo, indice.titulos[i]).ratio()
                if similaridade > similaridade_melhor:
                    melhor, similaridade_melhor = i, similaridade
            if melhor is not None and similaridade_melhor >= LIMIAR_M3:
                achado = (melhor, "M3", similaridade_melhor)

        if achado is None:
            ausentes.append(registro)
            continue

        i, etapa, similaridade = achado
        alvo = indice.registros[i]
        pares.append(
            {
                "fonte": fonte,
                "id_base": registro["source_id"],
                "id_alvo": alvo["source_id"],
                "handle": alvo.get("handle", ""),
                "etapa": etapa,
                "similaridade": f"{similaridade:.4f}",
                "titulo_base": registro["title"],
                "titulo_alvo": alvo["title"],
                "ano_base": registro["year"],
                "ano_alvo": alvo["year"],
                "tipo_alvo": alvo["type"],
                "doi": registro["doi"],
            }
        )

    assert len(pares) + len(ausentes) == len(base), "registro perdido no pareamento"
    return pares, ausentes


def url_do_par(par: dict) -> tuple[str, str]:
    """Endereços para a conferência manual: o registro na base e o item no repositório."""
    url_base = f"https://doi.org/{par['doi']}" if par.get("doi") else ""
    handle = par.get("handle") or ""
    url_alvo = f"https://repositorio.ufrn.br/handle/{handle}" if handle else ""
    return url_base, url_alvo


def amostrar(
    pares_m3: list[dict],
    pares_divergentes: list[dict],
    ausentes: list[dict],
    sorteio: random.Random,
) -> list[dict]:
    """Monta a planilha de conferência, em três estratos.

    A conferência é do pesquisador, item a item, abrindo o item do repositório ao lado
    do registro da base.

    - **par M3** — estima o falso positivo do limiar de similaridade.
    - **par com tipo divergente** — o registro da base pareou com item que o repositório
      não classificou como artigo. Costuma ser artigo depositado com ``dc.type`` errado,
      e nesse caso o par é bom; mas pode ser o trabalho de conclusão do aluno depositado
      com o DOI do artigo dele derivado, e nesse caso o artigo não está no repositório e
      o par é falso positivo. A distinção é de julgamento, não de regra.
    - **ausente** — estima o falso negativo do protocolo (item que está no repositório mas
      não pareou, por exemplo por título traduzido), que entra no artigo como margem de
      erro da cobertura.
    """
    linhas: list[dict] = []

    for par in sorteio.sample(pares_m3, min(TAMANHO_AMOSTRA, len(pares_m3))):
        url_base, url_alvo = url_do_par(par)
        linhas.append(
            {
                "estrato": "par M3",
                "fonte": par["fonte"],
                "id_base": par["id_base"],
                "titulo_base": par["titulo_base"],
                "ano_base": par["ano_base"],
                "url_base": url_base,
                "titulo_alvo": par["titulo_alvo"],
                "ano_alvo": par["ano_alvo"],
                "url_alvo": url_alvo,
                "similaridade": par["similaridade"],
                "veredito": "",
            }
        )

    for par in sorteio.sample(pares_divergentes, min(TAMANHO_AMOSTRA, len(pares_divergentes))):
        url_base, url_alvo = url_do_par(par)
        linhas.append(
            {
                "estrato": f"tipo divergente ({par['tipo_alvo']}, {par['etapa']})",
                "fonte": par["fonte"],
                "id_base": par["id_base"],
                "titulo_base": par["titulo_base"],
                "ano_base": par["ano_base"],
                "url_base": url_base,
                "titulo_alvo": par["titulo_alvo"],
                "ano_alvo": par["ano_alvo"],
                "url_alvo": url_alvo,
                "similaridade": par["similaridade"],
                "veredito": "",
            }
        )

    for ausente in sorteio.sample(ausentes, min(TAMANHO_AMOSTRA, len(ausentes))):
        linhas.append(
            {
                "estrato": "ausente",
                "fonte": ausente["fonte"],
                "id_base": ausente["source_id"],
                "titulo_base": ausente["title"],
                "ano_base": ausente["year"],
                "url_base": f"https://doi.org/{ausente['doi']}" if ausente["doi"] else "",
                "titulo_alvo": "",
                "ano_alvo": "",
                # a conferência do ausente é uma busca pelo título no repositório
                "url_alvo": "https://repositorio.ufrn.br/search",
                "similaridade": "",
                "veredito": "",
            }
        )

    return linhas


def relatar(
    dados: str,
    resumos: list[dict],
    indice_ri: Indice,
    tipos_alvo: collections.Counter,
    fora_do_recorte: int,
) -> None:
    """Grava dados/MATCHING.md, a proveniência da fase, com os números do artigo."""
    linhas = [
        "# Fase 2 — pareamento (proveniência)",
        "",
        "Gerado por `src/matching.py`. Os conjuntos ficam nos CSVs de `dados/`, não versionados.",
        "",
        f"Candidatos no repositório: **{len(indice_ri.registros)}** itens, todos os anos "
        "(`ri-todos.csv`). O recorte 2020–2025 delimita o universo das bases, não os candidatos.",
        "",
        "## Pares por etapa",
        "",
        "| cotejo | universo | M1 (DOI) | M2 (título+ano) | M3 (fuzzy ≥ 0,95) | pareados | ausentes | cobertura |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in resumos:
        etapas = r["etapas"]
        pareados = sum(etapas.values())
        cobertura = 100 * pareados / r["universo"] if r["universo"] else 0
        linhas.append(
            f"| {r['cotejo']} | {r['universo']} | {etapas['M1']} | {etapas['M2']} | "
            f"{etapas['M3']} | {pareados} | {r['ausentes']} | {cobertura:.1f}% |"
        )

    linhas += [
        "",
        "## Pares fora do recorte do repositório",
        "",
        f"**{fora_do_recorte}** pares têm o item do repositório depositado com data fora de "
        "2020–2025, quase sempre o ano anterior ao da publicação na base. São artigos que "
        "*estão* no repositório e que teriam sido contados como ausentes se o conjunto de "
        "candidatos fosse o recorte, e não o repositório inteiro. É a medida do viés que a "
        "ampliação do universo de candidatos evitou — viés que empurraria a defasagem para "
        "cima, na direção da hipótese do estudo.",
        "",
        "## Tipo do item pareado no repositório",
        "",
        "| tipo (dc.type) | pares |",
        "|---|---|",
    ]
    for tipo, n in tipos_alvo.most_common():
        linhas.append(f"| {tipo or '(vazio)'} | {n} |")
    linhas += [
        "",
        "Parte dos registros das bases pareia com item que o repositório **não** classificou "
        "como artigo. Na inspeção, a maioria é artigo depositado com `dc.type` errado, tendo "
        "o mesmo DOI e o mesmo título do registro da base, o que é achado sobre a qualidade "
        "dos metadados do repositório, não erro do pareamento. O caso a distinguir é o do "
        "trabalho de conclusão depositado com o DOI do artigo dele derivado: aí o artigo não "
        "está no repositório e o par é falso positivo. Todos esses pares vão para a "
        "conferência manual, em estrato próprio.",
        "",
        "## Cardinalidade",
        "",
        "Cada registro da base fica com um item do repositório. O mesmo item pode ser "
        "reclamado por mais de um registro, o que ocorre quando o repositório tem depósito "
        "duplicado ou quando a base traz o mesmo trabalho duas vezes. Impedir o reuso "
        "tornaria o resultado dependente da ordem de leitura dos arquivos.",
        "",
        "| cotejo | itens do alvo reclamados mais de uma vez |",
        "|---|---|",
    ]
    for r in resumos:
        linhas.append(f"| {r['cotejo']} | {r['reusados']} |")

    linhas += [
        "",
        "## Conferência manual pendente",
        "",
        f"`validacao-manual.csv` traz três estratos, até {TAMANHO_AMOSTRA} linhas cada, "
        f"sorteados com semente {SEMENTE}: pares da etapa M3, pares cujo item do repositório "
        "não é do tipo artigo, e registros classificados como ausentes. O veredito é "
        "preenchido à mão, item a item. A taxa de acerto dos M3 valida o limiar de "
        "similaridade; a taxa de acerto dos pares de tipo divergente separa o artigo mal "
        "classificado do trabalho de conclusão depositado com o DOI do artigo derivado; e a "
        "taxa de itens encontrados entre os ausentes é o falso negativo do protocolo, que "
        "entra no artigo como margem de erro da cobertura.",
        "",
    ]

    caminho = os.path.join(dados, "MATCHING.md")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    print(f"\nproveniência -> {caminho}")


def executar(dados: str) -> None:
    scopus = ler_csv(os.path.join(dados, "scopus-all.csv"))
    wos = ler_csv(os.path.join(dados, "wos-all.csv"))
    ri = ler_csv(os.path.join(dados, "ri-todos.csv"))
    print(f"universo: Scopus {len(scopus)}, WoS {len(wos)} | candidatos: RI {len(ri)}")

    indice_ri = Indice(ri)
    indice_wos = Indice(wos)
    resumos: list[dict] = []
    todos_m3: list[dict] = []
    todos_divergentes: list[dict] = []
    todos_ausentes: list[dict] = []
    tipos_alvo: collections.Counter = collections.Counter()
    fora_do_recorte = 0

    cotejos = [
        ("scopus-ri", "scopus", scopus, indice_ri, "match-scopus-ri.csv", "ausentes-scopus.csv"),
        ("wos-ri", "wos", wos, indice_ri, "match-wos-ri.csv", "ausentes-wos.csv"),
        ("scopus-wos", "scopus", scopus, indice_wos, "match-scopus-wos.csv", None),
    ]

    for cotejo, fonte, base, indice, saida_pares, saida_ausentes in cotejos:
        pares, ausentes = parear(base, indice, fonte)
        escrever_csv(os.path.join(dados, saida_pares), pares, CAMPOS_PAR)
        if saida_ausentes:  # os dois cotejos contra o repositório, não o de bases entre si
            escrever_csv(os.path.join(dados, saida_ausentes), ausentes, CAMPOS)
            todos_m3 += [p for p in pares if p["etapa"] == "M3"]
            todos_divergentes += [p for p in pares if p["tipo_alvo"] != "article"]
            for a in ausentes:
                todos_ausentes.append({**a, "fonte": fonte})
            tipos_alvo.update(p["tipo_alvo"] for p in pares)
            fora_do_recorte += sum(
                1 for p in pares if not 2020 <= ano_de({"year": p["ano_alvo"]}) <= 2025
            )

        alvos = collections.Counter(p["id_alvo"] for p in pares)
        resumos.append(
            {
                "cotejo": cotejo,
                "universo": len(base),
                "etapas": collections.Counter({"M1": 0, "M2": 0, "M3": 0})
                + collections.Counter(p["etapa"] for p in pares),
                "ausentes": len(ausentes),
                "reusados": sum(1 for n in alvos.values() if n > 1),
            }
        )
        etapas = resumos[-1]["etapas"]
        print(
            f"{cotejo}: M1 {etapas['M1']}, M2 {etapas['M2']}, M3 {etapas['M3']} | "
            f"ausentes {len(ausentes)}"
        )

    validacao = amostrar(todos_m3, todos_divergentes, todos_ausentes, random.Random(SEMENTE))
    caminho_validacao = os.path.join(dados, "validacao-manual.csv")
    with open(caminho_validacao, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_VALIDACAO)
        w.writeheader()
        w.writerows(validacao)
    print(f"{len(validacao)} linhas para conferência manual -> {caminho_validacao}")

    relatar(dados, resumos, indice_ri, tipos_alvo, fora_do_recorte)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com os CSVs consolidados")
    a = p.parse_args()
    executar(a.dados)
