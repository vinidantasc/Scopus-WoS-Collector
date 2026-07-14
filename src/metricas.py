"""Fase 3 — métricas de cobertura, tabelas e o insumo das figuras.

    python3 src/metricas.py --dados /caminho/dados

Lê os conjuntos da fase 2 e produz o que o artigo relata: cobertura do repositório
sobre o universo indexado, global e desagregada por ano de publicação, por tipo de
documento e por exclusividade de base; a sobreposição entre Scopus e Web of Science; e
a distribuição dos periódicos entre os registros ausentes.

O universo citável **não existe em CSV**: ele é reconstruído aqui do mesmo modo que na
fase 2, com ``filtrar_universo`` e as mesmas constantes, e conferido contra o total já
publicado. Recalcular em vez de ler um total gravado é o que garante que a fase 3 não
herde silenciosamente um número defasado — se o dado da fase 1 ou 2 mudar, a trava
estoura em vez de o artigo mudar de resultado sem que ninguém perceba.

Duas decisões de contagem, que mudam o número e por isso ficam ditas:

**A união das bases se conta por trabalho, não por registro.** Scopus e Web of Science
identificam o mesmo trabalho com identificadores próprios, e o cotejo entre as duas dá
a correspondência. Em 14 casos duas entradas da Scopus apontam para o mesmo registro da
WoS — o trabalho está duplicado numa das bases —, de modo que somar registros e
subtrair pares superestima a união. A união é formada aqui por componentes conexos do
grafo de identidade (as arestas são os pares), e cada componente é um trabalho.

**A cobertura unificada é do trabalho, não do registro.** Um trabalho da união conta
como coberto se qualquer um dos registros que o representam parear com o repositório.
O contrário — exigir que os dois lados pareiem — mediria o pareamento, não a presença.

A cobertura por ano de publicação não é monótona, e a série sozinha não explica por
quê. Por isso a fase cruza os pares com a data de **depósito** (``deposito-ri.csv``,
gerado por ``src/deposito.py``): é o ano em que o item entrou no repositório, e é ele
que mostra se o repique de um ano de publicação vem de uma carga concentrada de
depósitos, e não do fluxo corrente.

Somente biblioteca padrão.
"""

from __future__ import annotations

import argparse
import collections
import os

from common import ano_de, escrever_csv, ler_csv
from matching import (
    CITAVEIS_SCOPUS,
    CITAVEIS_WOS,
    TESES_RI,
    filtrar_universo,
)

ANOS = range(2020, 2026)  # recorte do estudo, o mesmo da fase 1
TOTAL_PERIODICOS = 20  # periódicos mais frequentes entre os ausentes, conforme o roteiro

# Totais publicados na fase 2. Servem de trava: a fase 3 recalcula tudo por outra via e
# tem de reencontrá-los. Divergência é defeito, não descoberta.
UNIVERSO_ESPERADO = {"scopus": 12243, "wos": 10571}
COBERTOS_ESPERADO = {"scopus": 910, "wos": 832}

# Vocabulário comum das três fontes. O tipo da WoS é composto ("Article; Early Access",
# "Article; Data Paper") e a família é o primeiro componente que se reconhece — a mesma
# agregação que a fase 1 usou para compor a tabela de tipos (COLETA.md §6).
TIPO_CANONICO = {
    "Article": "artigo",
    "Review": "revisão",
    "Conference Paper": "trabalho de congresso",
    "Proceedings Paper": "trabalho de congresso",
    "Meeting": "trabalho de congresso",
    "Book Chapter": "capítulo de livro",
    "Data Paper": "data paper",
}
ORDEM_TIPOS = ["artigo", "revisão", "trabalho de congresso", "capítulo de livro", "data paper"]

CAMPOS_METRICA = ["metrica", "recorte", "chave", "valor"]


def tipo_canonico(registro: dict) -> str:
    """Tipo do documento no vocabulário comum às duas bases; '' se não se reconhece."""
    for parte in registro.get("type", "").split(";"):
        canonico = TIPO_CANONICO.get(parte.strip())
        if canonico:
            return canonico
    return ""


class Obras:
    """Componentes conexos do grafo de identidade entre as fontes.

    Cada nó é um par (fonte, identificador); cada aresta, um par produzido pelo
    pareamento. Um componente é um trabalho, visto por quantas fontes o registrarem.
    A estrutura resolve, de uma vez, a união das bases, a sobreposição e as sete regiões
    do diagrama de Venn — que de outro modo teriam de ser contadas por três caminhos
    distintos, com três oportunidades de divergir.
    """

    def __init__(self) -> None:
        self.pai: dict[tuple[str, str], tuple[str, str]] = {}

    def no(self, fonte: str, identificador: str) -> tuple[str, str]:
        chave = (fonte, identificador)
        self.pai.setdefault(chave, chave)
        return chave

    def raiz(self, chave: tuple[str, str]) -> tuple[str, str]:
        while self.pai[chave] != chave:
            self.pai[chave] = self.pai[self.pai[chave]]  # compressão de caminho
            chave = self.pai[chave]
        return chave

    def unir(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.pai[ra] = rb

    def componentes(self) -> dict[tuple[str, str], set[str]]:
        """Raiz -> fontes presentes no componente."""
        agrupado: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
        for chave in self.pai:
            agrupado[self.raiz(chave)].add(chave[0])
        return agrupado


def carregar(dados: str) -> dict:
    """Reconstrói o universo citável, os candidatos e os pares da fase 2."""
    scopus, _ = filtrar_universo(ler_csv(os.path.join(dados, "scopus-all.csv")), CITAVEIS_SCOPUS)
    wos, _ = filtrar_universo(ler_csv(os.path.join(dados, "wos-all.csv")), CITAVEIS_WOS)
    ri = ler_csv(os.path.join(dados, "ri-todos.csv"))
    candidatos = [r for r in ri if r["type"] not in TESES_RI]

    universo = {"scopus": scopus, "wos": wos}
    for fonte, base in universo.items():
        assert len(base) == UNIVERSO_ESPERADO[fonte], (
            f"universo citável da {fonte} mudou: {len(base)} ≠ {UNIVERSO_ESPERADO[fonte]}"
        )

    pares = {
        "scopus": ler_csv(os.path.join(dados, "match-scopus-ri.csv")),
        "wos": ler_csv(os.path.join(dados, "match-wos-ri.csv")),
    }
    for fonte, lista in pares.items():
        assert len(lista) == COBERTOS_ESPERADO[fonte], (
            f"pares da {fonte} mudaram: {len(lista)} ≠ {COBERTOS_ESPERADO[fonte]}"
        )

    ausentes = {
        "scopus": ler_csv(os.path.join(dados, "ausentes-scopus.csv")),
        "wos": ler_csv(os.path.join(dados, "ausentes-wos.csv")),
    }
    for fonte in universo:
        assert len(pares[fonte]) + len(ausentes[fonte]) == len(universo[fonte]), (
            f"pares + ausentes ≠ universo citável da {fonte}"
        )

    caminho_deposito = os.path.join(dados, "deposito-ri.csv")
    if not os.path.exists(caminho_deposito):
        raise SystemExit("deposito-ri.csv não existe; rode antes: python3 src/deposito.py --dados …")

    return {
        "universo": universo,
        "candidatos": candidatos,
        "pares": pares,
        "ausentes": ausentes,
        "entre_bases": ler_csv(os.path.join(dados, "match-scopus-wos.csv")),
        "deposito": {r["source_id"]: r for r in ler_csv(caminho_deposito)},
    }


def montar_obras(conjuntos: dict) -> Obras:
    """Grafo de identidade: registro da Scopus, da WoS e item do repositório, unidos pelos pares."""
    obras = Obras()
    for fonte, base in conjuntos["universo"].items():
        for registro in base:
            obras.no(fonte, registro["source_id"])
    for item in conjuntos["candidatos"]:
        obras.no("ri", item["source_id"])

    for par in conjuntos["entre_bases"]:
        obras.unir(obras.no("scopus", par["id_base"]), obras.no("wos", par["id_alvo"]))
    for fonte, lista in conjuntos["pares"].items():
        for par in lista:
            obras.unir(obras.no(fonte, par["id_base"]), obras.no("ri", par["id_alvo"]))
    return obras


def regioes(obras: Obras) -> collections.Counter:
    """As sete regiões do diagrama de Venn, contadas em trabalhos (componentes)."""
    contagem: collections.Counter = collections.Counter()
    for fontes in obras.componentes().values():
        contagem["+".join(f for f in ("scopus", "wos", "ri") if f in fontes)] += 1
    return contagem


def por_ano(conjuntos: dict) -> dict[str, dict[int, tuple[int, int]]]:
    """Cobertos e universo por ano de publicação, em cada base."""
    tabela: dict[str, dict[int, tuple[int, int]]] = {}
    for fonte, base in conjuntos["universo"].items():
        universo = collections.Counter(ano_de(r) for r in base)
        cobertos = collections.Counter(ano_de({"year": p["ano_base"]}) for p in conjuntos["pares"][fonte])
        tabela[fonte] = {ano: (cobertos[ano], universo[ano]) for ano in ANOS}
    return tabela


def por_ano_uniao(conjuntos: dict, obras: Obras) -> dict[int, tuple[int, int]]:
    """Cobertos e universo por ano, contados em trabalhos da união.

    O ano do trabalho é o do registro da Scopus quando ele existe nas duas bases: a WoS
    indexa o mesmo trabalho ora no ano do acesso antecipado, ora no do fascículo, e tomar
    o ano dos dois lados poria o mesmo trabalho em dois anos distintos.
    """
    ano_do_no: dict[tuple[str, str], int] = {}
    for fonte, base in conjuntos["universo"].items():
        for registro in base:
            ano_do_no[(fonte, registro["source_id"])] = ano_de(registro)

    componentes: dict[tuple[str, str], set[tuple[str, str]]] = collections.defaultdict(set)
    for chave in obras.pai:
        componentes[obras.raiz(chave)].add(chave)

    universo: collections.Counter = collections.Counter()
    cobertos: collections.Counter = collections.Counter()
    for nos in componentes.values():
        fontes = {f for f, _ in nos}
        if not fontes & {"scopus", "wos"}:
            continue  # componente só do repositório: não está no universo medido
        preferidos = [n for n in nos if n[0] == "scopus"] or [n for n in nos if n[0] == "wos"]
        ano = ano_do_no[min(preferidos)]
        if ano not in ANOS:
            continue
        universo[ano] += 1
        if "ri" in fontes:
            cobertos[ano] += 1
    return {ano: (cobertos[ano], universo[ano]) for ano in ANOS}


def por_tipo(conjuntos: dict) -> dict[str, dict[str, tuple[int, int]]]:
    """Cobertos e universo por tipo de documento, em cada base.

    O tipo do registro da base não está no CSV de pares — o par guarda o ``dc.type`` do
    lado do repositório, que é justamente o campo que a fase 2 mostrou não ser confiável.
    O tipo vem, portanto, do universo, reindexado pelo identificador da base.
    """
    tabela: dict[str, dict[str, tuple[int, int]]] = {}
    for fonte, base in conjuntos["universo"].items():
        tipos = {r["source_id"]: tipo_canonico(r) for r in base}
        universo = collections.Counter(tipos.values())
        cobertos = collections.Counter(tipos[p["id_base"]] for p in conjuntos["pares"][fonte])
        tabela[fonte] = {
            tipo: (cobertos[tipo], universo[tipo]) for tipo in ORDEM_TIPOS if universo[tipo]
        }
    return tabela


def por_exclusividade(conjuntos: dict, obras: Obras) -> dict[str, tuple[int, int]]:
    """Cobertura dos trabalhos só-Scopus, só-WoS e indexados nas duas bases.

    Testa se o repositório cobre melhor a produção que as duas bases indexam — a mais
    visível, presumivelmente a de maior circulação — do que a exclusiva de uma delas.
    """
    estratos = {"só Scopus": [0, 0], "só WoS": [0, 0], "Scopus e WoS": [0, 0]}
    nomes = {frozenset({"scopus"}): "só Scopus", frozenset({"wos"}): "só WoS"}
    for fontes in obras.componentes().values():
        bases = fontes & {"scopus", "wos"}
        if not bases:
            continue  # componente só do repositório: item que não está em base nenhuma
        estrato = nomes.get(frozenset(bases), "Scopus e WoS")
        estratos[estrato][1] += 1
        if "ri" in fontes:
            estratos[estrato][0] += 1
    return {nome: (c, u) for nome, (c, u) in estratos.items()}


def por_deposito(conjuntos: dict) -> dict[int, collections.Counter]:
    """Ano de depósito dos itens pareados, por ano de publicação do registro na base.

    Responde à anomalia da série temporal: a cobertura cai de 2020 a 2024 e sobe em 2025.
    Se o repique vier de depósitos concentrados num período curto, e não do fluxo corrente
    do repositório, é aqui que aparece.

    Conta o cotejo com a Scopus apenas. O mesmo trabalho está nas duas bases em 8.574 dos
    casos, e somar os dois cotejos contaria duas vezes o mesmo depósito.
    """
    tabela: dict[int, collections.Counter] = {ano: collections.Counter() for ano in ANOS}
    for par in conjuntos["pares"]["scopus"]:
        ano_publicacao = ano_de({"year": par["ano_base"]})
        if ano_publicacao not in tabela:
            continue
        item = conjuntos["deposito"].get(par["id_alvo"])
        tabela[ano_publicacao][ano_de({"year": (item or {}).get("ano_deposito", "")})] += 1
    return tabela


def periodicos_ausentes(conjuntos: dict) -> dict[str, list[tuple[str, int]]]:
    """Periódicos mais frequentes entre os registros ausentes.

    O repositório não guarda o título do periódico (``venue`` é sempre vazio nos itens
    do DSpace da UFRN), de modo que a distribuição só existe do lado das bases — que é
    onde ela é necessária, porque a pergunta é onde a produção *não* depositada saiu.
    """
    return {
        fonte: collections.Counter(
            r["venue"] for r in lista if r["venue"]
        ).most_common(TOTAL_PERIODICOS)
        for fonte, lista in conjuntos["ausentes"].items()
    }


def pct(cobertos: int, universo: int) -> float:
    return 100 * cobertos / universo if universo else 0.0


def gravar_metricas(dados: str, calculos: dict) -> None:
    """Grava dados/metricas.csv, em formato longo: uma linha por medida."""
    linhas: list[dict] = []

    def anotar(metrica: str, recorte: str, chave: str, valor: object) -> None:
        linhas.append({"metrica": metrica, "recorte": recorte, "chave": chave, "valor": valor})

    for fonte, (cobertos, universo) in calculos["global"].items():
        anotar("universo", fonte, "total", universo)
        anotar("cobertos", fonte, "total", cobertos)
        anotar("ausentes", fonte, "total", universo - cobertos)
        anotar("cobertura_pct", fonte, "total", f"{pct(cobertos, universo):.2f}")
        anotar("defasagem_pct", fonte, "total", f"{100 - pct(cobertos, universo):.2f}")

    for fonte, tabela in calculos["ano"].items():
        for ano, (cobertos, universo) in tabela.items():
            anotar("universo", fonte, str(ano), universo)
            anotar("cobertos", fonte, str(ano), cobertos)
            anotar("cobertura_pct", fonte, str(ano), f"{pct(cobertos, universo):.2f}")

    for fonte, tabela in calculos["tipo"].items():
        for tipo, (cobertos, universo) in tabela.items():
            anotar("universo_tipo", fonte, tipo, universo)
            anotar("cobertos_tipo", fonte, tipo, cobertos)
            anotar("cobertura_tipo_pct", fonte, tipo, f"{pct(cobertos, universo):.2f}")

    uniao = calculos["uniao"]
    anotar("universo", "uniao", "total", uniao["trabalhos"])
    anotar("cobertos", "uniao", "total", uniao["cobertos"])
    anotar("ausentes", "uniao", "total", uniao["trabalhos"] - uniao["cobertos"])
    anotar("cobertura_pct", "uniao", "total", f"{pct(uniao['cobertos'], uniao['trabalhos']):.2f}")
    anotar(
        "defasagem_pct", "uniao", "total",
        f"{100 - pct(uniao['cobertos'], uniao['trabalhos']):.2f}",
    )
    anotar("jaccard", "uniao", "scopus x wos", f"{uniao['jaccard']:.4f}")
    anotar("candidatos_ri", "ri", "total", calculos["candidatos_ri"])

    for ano, (cobertos, universo) in calculos["ano_uniao"].items():
        anotar("universo", "uniao", str(ano), universo)
        anotar("cobertos", "uniao", str(ano), cobertos)
        anotar("cobertura_pct", "uniao", str(ano), f"{pct(cobertos, universo):.2f}")

    for estrato, (cobertos, universo) in calculos["exclusividade"].items():
        anotar("universo_exclusividade", "uniao", estrato, universo)
        anotar("cobertos_exclusividade", "uniao", estrato, cobertos)
        anotar("cobertura_exclusividade_pct", "uniao", estrato, f"{pct(cobertos, universo):.2f}")

    for regiao, n in sorted(calculos["regioes"].items()):
        anotar("regiao_venn", "obras", regiao, n)

    for ano, contagem in calculos["deposito"].items():
        for ano_deposito, n in sorted(contagem.items()):
            anotar("deposito", str(ano), str(ano_deposito or "sem data"), n)

    for fonte, contagem in calculos["periodicos"].items():
        for periodico, n in contagem:
            anotar("periodico_ausente", fonte, periodico, n)

    escrever_csv(os.path.join(dados, "metricas.csv"), linhas, CAMPOS_METRICA)


def relatar(dados: str, calculos: dict) -> None:
    """Grava manuscrito/tabelas.md, as tabelas do artigo prontas para o texto."""
    global_ = calculos["global"]
    uniao = calculos["uniao"]
    ano = calculos["ano"]
    tipo = calculos["tipo"]

    linhas = [
        "# Fase 3 — métricas, tabelas e figuras",
        "",
        "Gerado por `src/metricas.py`. Os conjuntos ficam nos CSVs de `dados/`, não versionados.",
        "",
        f"Do universo indexado de **{uniao['trabalhos']}** trabalhos distintos publicados por "
        f"autores da UFRN entre 2020 e 2025, o Repositório Institucional tem "
        f"**{uniao['cobertos']}** — cobertura de **{pct(uniao['cobertos'], uniao['trabalhos']):.2f}%**. "
        f"A defasagem é de **{uniao['trabalhos'] - uniao['cobertos']}** trabalhos, "
        f"**{100 - pct(uniao['cobertos'], uniao['trabalhos']):.2f}%** do que as duas bases indexam.",
        "",
        "## Tabela 1 — universo, cobertura e defasagem por base",
        "",
        "| base | universo citável | no repositório | ausentes | cobertura | defasagem |",
        "|---|---|---|---|---|---|",
    ]
    for fonte, (cobertos, universo) in global_.items():
        linhas.append(
            f"| {fonte} | {universo} | {cobertos} | {universo - cobertos} | "
            f"{pct(cobertos, universo):.2f}% | {100 - pct(cobertos, universo):.2f}% |"
        )
    linhas.append(
        f"| união (trabalhos) | {uniao['trabalhos']} | {uniao['cobertos']} | "
        f"{uniao['trabalhos'] - uniao['cobertos']} | "
        f"{pct(uniao['cobertos'], uniao['trabalhos']):.2f}% | "
        f"{100 - pct(uniao['cobertos'], uniao['trabalhos']):.2f}% |"
    )
    linhas += [
        "",
        f"A união não é a soma menos a interseção de registros. Scopus e WoS têm identificador "
        f"próprio, e o cotejo entre elas produziu {uniao['pares']} pares, mas apenas "
        f"{uniao['uids']} registros distintos da WoS: em {uniao['pares'] - uniao['uids']} casos "
        "duas entradas da Scopus apontam para o mesmo trabalho. A união é contada em trabalhos, "
        "por componentes conexos do grafo de identidade, e não em registros.",
        "",
        f"**Sobreposição das bases (Jaccard):** {uniao['jaccard']:.4f}. Das duas, a Scopus é a "
        f"mais abrangente: {global_['scopus'][1]} documentos citáveis contra "
        f"{global_['wos'][1]} da WoS.",
        "",
        "## Tabela 2 — cobertura por ano de publicação",
        "",
        "| ano | Scopus | WoS | união |",
        "|---|---|---|---|",
    ]
    for a in ANOS:
        cs, us = ano["scopus"][a]
        cw, uw = ano["wos"][a]
        cu, uu = calculos["ano_uniao"][a]
        linhas.append(
            f"| {a} | {cs}/{us} = {pct(cs, us):.2f}% | {cw}/{uw} = {pct(cw, uw):.2f}% | "
            f"{cu}/{uu} = {pct(cu, uu):.2f}% |"
        )

    melhor = max(ANOS, key=lambda a: pct(*calculos["ano_uniao"][a]))
    pior = min(ANOS, key=lambda a: pct(*calculos["ano_uniao"][a]))
    linhas += [
        "",
        f"A série não decresce de forma monótona. A cobertura é máxima em {melhor} "
        f"({pct(*calculos['ano_uniao'][melhor]):.2f}%), cai até {pior} "
        f"({pct(*calculos['ano_uniao'][pior]):.2f}%) e volta a subir depois. Não é o padrão que se "
        "esperaria de um repositório alimentado por depósito corrente, em que o ano recente teria "
        "a menor cobertura por efeito de atraso.",
        "",
        "## Tabela 3 — ano de depósito dos artigos cobertos, por ano de publicação",
        "",
        "Onde a série se explica. Cada linha é um ano de publicação; as colunas dizem em que ano "
        "o item entrou no repositório (`dc.date.accessioned`). Os números são do cotejo com a "
        "Scopus, a base mais abrangente.",
        "",
        "| ano de publicação | " + " | ".join(str(a) for a in sorted(
            {d for c in calculos["deposito"].values() for d in c if d}
        )) + " |",
        "|---" * (1 + len({d for c in calculos["deposito"].values() for d in c if d})) + "|",
    ]
    colunas = sorted({d for c in calculos["deposito"].values() for d in c if d})
    for a in ANOS:
        contagem = calculos["deposito"][a]
        linhas.append(f"| {a} | " + " | ".join(str(contagem.get(c, 0)) for c in colunas) + " |")

    linhas += [
        "",
        "## Tabela 4 — cobertura por tipo de documento",
        "",
        "| tipo | Scopus | WoS |",
        "|---|---|---|",
    ]
    def celula(par: tuple[int, int] | None) -> str:
        # a WoS não tem, no recorte, tipo algum da família do capítulo de livro nem do data
        # paper: o que ela declara é "Article; Book" e "Article; Data Paper", que a agregação
        # por família põe em artigo. Universo vazio não é cobertura zero, e não se escreve 0%.
        if not par or not par[1]:
            return "—"
        return f"{par[0]}/{par[1]} = {pct(*par):.2f}%"

    for t in ORDEM_TIPOS:
        if not tipo["scopus"].get(t) and not tipo["wos"].get(t):
            continue
        linhas.append(f"| {t} | {celula(tipo['scopus'].get(t))} | {celula(tipo['wos'].get(t))} |")

    linhas += [
        "",
        "O tipo de documento organiza a defasagem. O artigo de periódico, que é o que o "
        "repositório de fato deposita, tem a cobertura mais alta; o trabalho de congresso e o "
        "capítulo de livro são quase inteiramente ausentes.",
        "",
        "Nota: a WoS declara tipos compostos, e a agregação por família soma à linha de "
        "*artigo* alguns registros que a Scopus classificaria noutra linha — *Article; Book* "
        "(40) e *Article; Data Paper* (14) no recorte. Por isso a WoS não tem célula própria "
        "de capítulo de livro nem de data paper: esses documentos existem, mas embutidos na "
        "família do artigo. A célula vazia (—) é universo inexistente naquela base, não "
        "cobertura zero.",
        "",
        "## Tabela 5 — cobertura por exclusividade de base",
        "",
        "| estrato | trabalhos | no repositório | cobertura |",
        "|---|---|---|---|",
    ]
    for estrato, (cobertos, universo) in calculos["exclusividade"].items():
        linhas.append(
            f"| {estrato} | {universo} | {cobertos} | {pct(cobertos, universo):.2f}% |"
        )

    r = calculos["regioes"]
    ri_total = r["ri"] + r["scopus+ri"] + r["wos+ri"] + r["scopus+wos+ri"]
    linhas += [
        "",
        "## Regiões do diagrama de Venn (figura 2)",
        "",
        "Contadas em trabalhos. O repositório entra com os **candidatos** ao pareamento, isto é, "
        "os itens de qualquer ano com tese, dissertação e trabalho de conclusão excluídos — o "
        f"mesmo conjunto contra o qual a fase 2 pareou. São {calculos['candidatos_ri']} "
        f"candidatos mais {ri_total - calculos['candidatos_ri']} item que a conferência "
        "reclassificou (o artigo depositado na coleção de trabalhos de conclusão, handle 60006, "
        f"etapa C), de onde os **{ri_total}** do círculo.",
        "",
        "| região | trabalhos |",
        "|---|---|",
        f"| só Scopus | {r['scopus']} |",
        f"| só WoS | {r['wos']} |",
        f"| só repositório | {r['ri']} |",
        f"| Scopus e WoS | {r['scopus+wos']} |",
        f"| Scopus e repositório | {r['scopus+ri']} |",
        f"| WoS e repositório | {r['wos+ri']} |",
        f"| Scopus, WoS e repositório | {r['scopus+wos+ri']} |",
        "",
        f"A região do repositório sozinho — **{r['ri']}** itens — não é erro nem lacuna das bases: "
        "é a produção que o repositório guarda e que Scopus e WoS não indexam, ou não indexam no "
        "recorte (livro, produto educacional, artigo em periódico nacional fora das bases, item "
        "depositado fora de 2020–2025). O artigo mede a cobertura das bases pelo repositório, não "
        "o contrário.",
        "",
        "## Periódicos mais frequentes entre os ausentes",
        "",
        "Onde está a produção que o repositório não tem. O repositório não guarda o título do "
        "periódico, de modo que a distribuição vem do lado das bases.",
        "",
        "| periódico | ausentes (Scopus) |",
        "|---|---|",
    ]
    for periodico, n in calculos["periodicos"]["scopus"]:
        linhas.append(f"| {periodico} | {n} |")

    caminho = os.path.join(dados, os.pardir, "manuscrito", "tabelas.md")
    caminho = os.path.abspath(caminho)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    print(f"\ntabelas -> {caminho}")


def executar(dados: str) -> None:
    conjuntos = carregar(dados)
    obras = montar_obras(conjuntos)
    contagem_regioes = regioes(obras)

    global_ = {
        fonte: (len(conjuntos["pares"][fonte]), len(base))
        for fonte, base in conjuntos["universo"].items()
    }

    trabalhos_uniao = sum(
        n for regiao, n in contagem_regioes.items() if regiao != "ri"
    )
    cobertos_uniao = sum(
        n for regiao, n in contagem_regioes.items()
        if "ri" in regiao.split("+") and regiao != "ri"
    )
    interseccao = contagem_regioes["scopus+wos"] + contagem_regioes["scopus+wos+ri"]
    uids = len({p["id_alvo"] for p in conjuntos["entre_bases"]})
    # cada par entre as bases funde dois trabalhos até então distintos: a união tem de ser a
    # soma dos universos menos o número de pares. Se falhar, o grafo tem ciclo — um registro
    # pareado duas vezes —, e a contagem de trabalhos deixaria de ser a de trabalhos
    assert trabalhos_uniao == (
        len(conjuntos["universo"]["scopus"])
        + len(conjuntos["universo"]["wos"])
        - len(conjuntos["entre_bases"])
    ), "a união não fecha: o grafo de identidade tem ciclo"
    assert cobertos_uniao == sum(
        contagem_regioes[r] for r in ("scopus+ri", "wos+ri", "scopus+wos+ri")
    ), "trabalho coberto contado fora das regiões do repositório"
    uniao = {
        "trabalhos": trabalhos_uniao,
        "cobertos": cobertos_uniao,
        "pares": len(conjuntos["entre_bases"]),
        "uids": uids,
        "jaccard": interseccao / trabalhos_uniao if trabalhos_uniao else 0.0,
    }

    calculos = {
        "global": global_,
        "uniao": uniao,
        "candidatos_ri": len(conjuntos["candidatos"]),
        "ano": por_ano(conjuntos),
        "ano_uniao": por_ano_uniao(conjuntos, obras),
        "tipo": por_tipo(conjuntos),
        "exclusividade": por_exclusividade(conjuntos, obras),
        "regioes": contagem_regioes,
        "deposito": por_deposito(conjuntos),
        "periodicos": periodicos_ausentes(conjuntos),
    }

    print(
        f"cobertura: Scopus {pct(*global_['scopus']):.2f}%, WoS {pct(*global_['wos']):.2f}%, "
        f"união {pct(uniao['cobertos'], uniao['trabalhos']):.2f}% "
        f"({uniao['cobertos']}/{uniao['trabalhos']} trabalhos)"
    )
    print(f"sobreposição das bases (Jaccard): {uniao['jaccard']:.4f}")

    gravar_metricas(dados, calculos)
    relatar(dados, calculos)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com os CSVs da fase 2")
    a = p.parse_args()
    executar(a.dados)
