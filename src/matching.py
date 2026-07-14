"""Fase 2 — pareamento dos registros das bases com os itens do repositório.

    python3 src/matching.py --dados /caminho/dados

Para cada registro da Scopus e da Web of Science publicado no recorte do estudo,
decide se existe item correspondente no Repositório Institucional. O que não parear
é a defasagem de cobertura, objeto do artigo. O mesmo procedimento pareia Scopus
com Web of Science, para medir a sobreposição entre as bases.

O pareamento é local, sobre os CSVs da fase 1, e não por consulta ao repositório
registro a registro: a busca remota multiplicaria as requisições e teria erro
próprio, do motor de indexação, sobreposto ao erro que se quer medir.

Universo e candidatos são coisas distintas, e cada um tem seu recorte.

O universo medido é o das bases no período 2020–2025, restrito aos **documentos
citáveis** (artigo, revisão, trabalho de congresso, capítulo de livro, data paper).
Errata, editorial, carta, nota e resumo de congresso ficam de fora: não são o produto
que o repositório deposita, e entravam no pareamento casando pelo título com o artigo
homônimo já depositado, o que produzia par falso.

Os candidatos são os itens do repositório de **qualquer ano** (``ri-todos.csv``),
porque o artigo publicado em 2020 e depositado com data divergente está lá e contá-lo
como ausente superestimaria a defasagem. Mas **tese, dissertação e trabalho de
conclusão não são candidatos**: na UFRN o trabalho acadêmico costuma levar o mesmo
título do artigo dele derivado — muitas vezes em inglês, e por vezes o próprio DOI do
artigo nos metadados — de modo que aceitá-lo como par afirmaria que o artigo está no
repositório quando o que está lá é a tese. A conferência mediu o erro por censo: dos 47
pares desse tipo, 45 eram a tese homônima e 2 eram o artigo depositado com ``dc.type``
errado. A regra erra em 4,3% dos casos, e erra para menos, não para mais: subestima a
cobertura em vez de inflá-la. Como o censo identifica um a um os registros em que ela
erra, o erro não fica como resíduo — os 2 voltam a contar como cobertos na etapa C.

Três etapas, aplicadas em ordem; o registro sai na primeira que casar:

    M1  DOI normalizado igual                                     — sem restrição
    M2  título normalizado igual, |Δano| ≤ 1 e classe compatível
    M3  título com similaridade ≥ 0,95, |Δano| ≤ 1 e classe compatível

A tolerância de um ano acomoda a divergência entre a data de publicação antecipada,
que as bases registram, e a data do fascículo, que o repositório costuma depositar.

As etapas por título exigem **classe de documento compatível** (periódico com
periódico, congresso com congresso, livro com livro), porque o trabalho apresentado em
congresso leva o mesmo título do artigo de periódico que dele resulta e casaria com
ele: no primeiro turno de conferência, três registros de congresso do CLEO 2021
pareavam com o artigo homônimo publicado na *Nature Communications* e depositado no
repositório, afirmando presença de um documento que não está lá. Classe desconhecida
de um dos lados não desqualifica: metadado faltante do repositório não pode virar
ausência do artigo.

No M1 não há restrição alguma, de ano ou de classe: um DOI encontrado prova que o item
está lá.

A trava de classe não esgota o problema do título compartilhado. Duas publicações
distintas podem levar o mesmo título dentro da mesma classe: a revisão sistemática da
Cochrane e o artigo de periódico que a resume têm nome idêntico, ano idêntico e DOI
diferente, e o repositório tem só o segundo. Por isso o estrato dos pares por título é
conferido por censo — são 14 por base —, e o par reprovado volta a ser ausência, pelo
``falsos-positivos-conferencia.csv``. A divergência de DOI **não** serve como regra
automática: nos demais pares do estrato quem diverge é o DOI do repositório, que está
truncado, sem hífen, com espaço escapado, ou tomado de outro artigo.

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

# Documentos citáveis, que formam o universo medido. Na WoS o campo é composto
# ("Article; Early Access", "Article; Meeting"): basta um componente citável.
CITAVEIS_SCOPUS = {"Article", "Review", "Conference Paper", "Book Chapter", "Data Paper"}
CITAVEIS_WOS = {"Article", "Review", "Proceedings Paper", "Meeting", "Book Chapter", "Data Paper"}

# Trabalho acadêmico não é candidato: leva o título (às vezes o DOI) do artigo derivado.
TESES_RI = {"bachelorThesis", "masterThesis", "doctoralThesis", "postGraduateThesis"}

# Classe do documento, para as etapas por título. O trabalho apresentado em congresso
# leva o mesmo título do artigo de periódico que dele resulta, e casaria com ele.
CLASSE_BASE = {
    "Article": "periodico",
    "Review": "periodico",
    "Data Paper": "periodico",
    "Conference Paper": "congresso",
    "Proceedings Paper": "congresso",
    "Meeting": "congresso",
    "Book Chapter": "livro",
}
CLASSE_RI = {
    "article": "periodico",
    "conferenceObject": "congresso",
    "conferenceProceeding": "congresso",
    "book": "livro",
    "bookPart": "livro",
}

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


def citavel(registro: dict, citaveis: set[str]) -> bool:
    """O registro é documento citável? Na WoS o tipo é composto, separado por ';'."""
    partes = {p.strip() for p in registro.get("type", "").split(";")}
    return bool(partes & citaveis)


def filtrar_universo(base: list[dict], citaveis: set[str]) -> tuple[list[dict], collections.Counter]:
    """Separa o universo medido dos documentos não citáveis, e conta o que saiu."""
    dentro = [r for r in base if citavel(r, citaveis)]
    fora = collections.Counter(r.get("type", "") for r in base if not citavel(r, citaveis))
    return dentro, fora


def classe_de(registro: dict, mapa: dict[str, str]) -> str:
    """Classe do documento (periódico, congresso, livro); vazio se o tipo não é conhecido."""
    for parte in registro.get("type", "").split(";"):
        classe = mapa.get(parte.strip())
        if classe:
            return classe
    return ""


class Indice:
    """Índice dos candidatos: por DOI, por título e por token do título.

    ``classes`` mapeia o vocabulário de tipo do próprio conjunto (o do repositório, ou o
    da base, quando se cotejam duas bases) para a classe de documento.
    """

    def __init__(self, registros: list[dict], classes: dict[str, str] = CLASSE_RI) -> None:
        self.registros = registros
        self.classes = classes
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

    def compativel(self, i: int, ano_base: int, classe_base: str = "") -> bool:
        """Ano dentro da tolerância e classe de documento compatível.

        Ano ou classe ausente não desqualifica: o dado faltante do repositório não pode
        virar ausência do artigo. Classes conhecidas e diferentes desqualificam — o
        trabalho de congresso não é o artigo de periódico de mesmo título.
        """
        ano = self.anos[i]
        if not (ano == 0 or ano_base == 0 or abs(ano - ano_base) <= TOLERANCIA_ANO):
            return False
        classe_alvo = classe_de(self.registros[i], self.classes)
        if classe_base and classe_alvo and classe_base != classe_alvo:
            return False
        return True

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
        classe = classe_de(registro, CLASSE_BASE)
        achado = None

        # o DOI prova a presença: não se exige compatibilidade de ano nem de classe
        if registro["doi"] and registro["doi"] in indice.por_doi:
            achado = (indice.por_doi[registro["doi"]], "M1", 1.0)

        if achado is None and titulo:
            for i in indice.por_titulo.get(titulo, ()):
                if indice.compativel(i, ano, classe):
                    achado = (i, "M2", 1.0)
                    break

        if achado is None and titulo:
            melhor, similaridade_melhor = None, 0.0
            for i in indice.candidatos(titulo):
                if not indice.compativel(i, ano, classe):
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


def ler_correcoes(dados: str) -> dict[tuple[str, str], str]:
    """Pares que a conferência confirmou e que a regra das teses exclui.

    A regra que tira tese, dissertação e TCC do conjunto de candidatos erra num caso:
    o **artigo** depositado com ``dc.type`` de trabalho acadêmico. O erro foi medido
    por censo — o estrato de tese homônima foi conferido inteiro, 47 de 47 —, de modo
    que os registros em que a regra erra são conhecidos um a um, e não estimados. Estão
    em ``correcoes-conferencia.csv``, e voltam a contar como cobertos.

    A correção sobe a cobertura, isto é, corrige **contra** a hipótese do estudo. Sem
    ela, o artigo publicaria como ausente um item que a própria conferência achou no
    repositório.
    """
    caminho = os.path.join(dados, "correcoes-conferencia.csv")
    if not os.path.exists(caminho):
        return {}
    return {(l["fonte"], l["id_base"]): l["handle"] for l in ler_csv(caminho)}


def aplicar_correcoes(
    pares: list[dict],
    ausentes: list[dict],
    fonte: str,
    correcoes: dict[tuple[str, str], str],
    por_handle: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Move para os pares o registro que a conferência confirmou estar no repositório."""
    if not correcoes:
        return pares, ausentes
    restantes: list[dict] = []
    for registro in ausentes:
        handle = correcoes.get((fonte, registro["source_id"]))
        alvo = por_handle.get(handle or "")
        if not alvo:
            restantes.append(registro)
            continue
        pares.append(
            {
                "fonte": fonte,
                "id_base": registro["source_id"],
                "id_alvo": alvo["source_id"],
                "handle": alvo.get("handle", ""),
                "etapa": "C",  # correção da conferência, não etapa automática
                "similaridade": "1.0000",
                "titulo_base": registro["title"],
                "titulo_alvo": alvo["title"],
                "ano_base": registro["year"],
                "ano_alvo": alvo["year"],
                "tipo_alvo": alvo["type"],
                "doi": registro["doi"],
            }
        )
    return pares, restantes


def ler_falsos_positivos(dados: str) -> set[tuple[str, str]]:
    """Pares que a conferência do estrato M2/M3 reprovou, e que voltam a ser ausência.

    Espelho da etapa C, e de sinal contrário. A etapa por título casa dois trabalhos
    distintos quando eles compartilham o título: a revisão sistemática Cochrane e o
    artigo de periódico que a resume levam o mesmo nome, e o repositório tem só o
    segundo. O DOI de cada lado prova que são publicações diferentes.

    A correção **desce** a cobertura, isto é, corrige a favor da hipótese do estudo, e
    por isso só entra registro a registro, com o veredito do conferente e a resolução
    dos dois DOI, nunca por regra automática: dos 14 pares por base do estrato, a
    divergência de DOI reprova um só. Nos demais o DOI do repositório é que está
    corrompido — truncado, sem hífen, com espaço escapado, ou tomado de outro artigo —,
    e descartá-los por regra jogaria fora par legítimo.
    """
    caminho = os.path.join(dados, "falsos-positivos-conferencia.csv")
    if not os.path.exists(caminho):
        return set()
    return {(l["fonte"], l["id_base"]) for l in ler_csv(caminho)}


def aplicar_falsos_positivos(
    pares: list[dict],
    ausentes: list[dict],
    fonte: str,
    falsos: set[tuple[str, str]],
    universo: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Devolve a ausente o par que a conferência reprovou."""
    if not falsos:
        return pares, ausentes
    mantidos: list[dict] = []
    for par in pares:
        if (fonte, par["id_base"]) in falsos:
            ausentes.append(universo[par["id_base"]])
        else:
            mantidos.append(par)
    return mantidos, ausentes


def url_do_par(par: dict) -> tuple[str, str]:
    """Endereços para a conferência manual: o registro na base e o item no repositório."""
    url_base = f"https://doi.org/{par['doi']}" if par.get("doi") else ""
    handle = par.get("handle") or ""
    url_alvo = f"https://repositorio.ufrn.br/handle/{handle}" if handle else ""
    return url_base, url_alvo


def amostrar(
    pares_m3: list[dict],
    pares_tese: list[dict],
    ausentes: list[dict],
    sorteio: random.Random,
) -> list[dict]:
    """Monta a planilha de conferência, em três estratos.

    A conferência é do pesquisador, item a item, abrindo o item do repositório ao lado
    do registro da base.

    - **par M3** — estima o falso positivo do limiar de similaridade.
    - **tese homônima** — o registro da base não pareou com candidato válido, mas existe
      no repositório uma tese, dissertação ou trabalho de conclusão de mesmo título. Não
      é par: o protocolo já o classificou como ausente. O estrato existe para medir o
      erro dessa regra, que é o caso do artigo depositado com ``dc.type`` de tese e que
      assim se perde. No primeiro turno de conferência, 1 dos 50 casos era isso.
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

    for par in sorteio.sample(pares_tese, min(TAMANHO_AMOSTRA, len(pares_tese))):
        url_base, url_alvo = url_do_par(par)
        linhas.append(
            {
                "estrato": f"tese homônima ({par['tipo_alvo']}, {par['etapa']})",
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
    n_teses: int,
    fora_universo: dict[str, collections.Counter],
    teses_homonimas: collections.Counter,
    tipos_alvo: collections.Counter,
    fora_do_recorte: int,
) -> None:
    """Grava dados/MATCHING.md, a proveniência da fase, com os números do artigo."""
    linhas = [
        "# Fase 2 — pareamento (proveniência)",
        "",
        "Gerado por `src/matching.py`. Os conjuntos ficam nos CSVs de `dados/`, não versionados.",
        "",
        f"Candidatos no repositório: **{len(indice_ri.registros)}** itens de qualquer ano, "
        f"depois de excluídas {n_teses} teses, dissertações e trabalhos de conclusão "
        "(`ri-todos.csv`). O recorte 2020–2025 delimita o universo das bases, não os "
        "candidatos: o artigo depositado com data divergente continua elegível.",
        "",
        "## Universo medido: documentos citáveis",
        "",
        "O universo é o das bases no recorte, restrito a artigo, revisão, trabalho de "
        "congresso, capítulo de livro e data paper. O que ficou de fora:",
        "",
        "| fonte | tipo excluído | registros |",
        "|---|---|---|",
    ]
    for fonte, contagem in fora_universo.items():
        for tipo, n in contagem.most_common():
            linhas.append(f"| {fonte} | {tipo or '(vazio)'} | {n} |")
    linhas += [
        "",
        "Errata, editorial, carta, nota e resumo de congresso não são o produto que o "
        "repositório deposita, e no primeiro turno de conferência apareceram casando pelo "
        "título com o artigo homônimo já depositado — a errata de um artigo tem o título do "
        "artigo, e o resumo de congresso também. Mantê-los no universo produzia par falso e "
        "contaminava a cobertura nas duas direções.",
        "",
        "## Pares por etapa",
        "",
        "| cotejo | universo | M1 (DOI) | M2 (título+ano) | M3 (fuzzy ≥ 0,95) | C (conferência) | pareados | ausentes | cobertura |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in resumos:
        etapas = r["etapas"]
        pareados = sum(etapas.values())
        cobertura = 100 * pareados / r["universo"] if r["universo"] else 0
        linhas.append(
            f"| {r['cotejo']} | {r['universo']} | {etapas['M1']} | {etapas['M2']} | "
            f"{etapas['M3']} | {etapas['C']} | {pareados} | {r['ausentes']} | "
            f"{cobertura:.2f}% |"
        )

    linhas += [
        "",
        "## Tese homônima: o artigo que o repositório não tem",
        "",
        "Registros das bases que não pareiam com candidato válido, mas para os quais existe "
        "no repositório uma tese, dissertação ou trabalho de conclusão de **mesmo título**:",
        "",
        "| cotejo | registros |",
        "|---|---|",
    ]
    for cotejo, n in teses_homonimas.most_common():
        linhas.append(f"| {cotejo} | {n} |")
    linhas += [
        "",
        "Não são pares, e sim ausências: o que está depositado é o trabalho acadêmico, não o "
        "artigo dele derivado. Na UFRN a tese de engenharia costuma ser escrita em inglês com "
        "o título do artigo, e parte dos trabalhos de conclusão traz nos metadados o próprio "
        "DOI do artigo publicado. Aceitá-los como par afirmaria presença onde há ausência.",
        "",
        "É o mecanismo da lacuna que o estudo quer descrever: o fluxo de depósito do "
        "repositório captura o que é obrigatório (tese, dissertação, trabalho de conclusão) e "
        "não captura o artigo que dali sai.",
        "",
        "A regra tem erro conhecido, medido **por censo** e **corrigido**. O estrato foi "
        "conferido inteiro, e não por amostra: dos 47 casos, 45 são de fato a tese homônima, "
        "e 2 registros (o mesmo artigo, indexado nas duas bases) são o artigo publicado "
        "depositado com `dc.type` de trabalho de conclusão — arquivo em layout de editora, na "
        "coleção de TCC. Como o censo identifica um a um os registros em que a regra erra, "
        "eles não ficam como erro residual: voltam a contar como cobertos pela etapa **C**, a "
        "partir de `correcoes-conferencia.csv`. A correção **sobe** a cobertura, isto é, "
        "corrige contra a hipótese do estudo.",
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
        "`conferenceObject` é o tipo correto do trabalho de congresso, não divergência.",
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
        "## Conferência manual",
        "",
        "**Primeiro turno (113 linhas, `validacao-manual-r1.csv`), concluído.** Estratos: 13 "
        "pares M3, os 50 pares de tipo divergente (censo, não amostra) e 50 ausentes. "
        "Resultado: **7 pares corretos, 56 falsos positivos e 50 ausências confirmadas**. Foi "
        "essa conferência que motivou as duas correções acima: o filtro de documentos "
        "citáveis no universo e a exclusão das teses do conjunto de candidatos. Triagem "
        "assistida por IA, confirmada pelo autor; a evidência item a item está em "
        "`triagem-assistida.csv`.",
        "",
        "Detalhe por estrato, que é o que justifica a correção do protocolo:",
        "",
        "| estrato do 1º turno | n | veredito |",
        "|---|---|---|",
        "| pares M3 (similaridade ≥ 0,95) | 13 | 2 corretos, 6 falsos positivos por tese "
        "homônima, 5 pares incorretos |",
        "| tipo divergente, tese/TCC (censo) | 47 | 45 tese homônima, 2 artigos depositados "
        "com `dc.type` errado |",
        "| tipo divergente, `conferenceObject` (censo) | 3 | 3 corretos (tipo certo do "
        "trabalho de congresso, não divergência) |",
        "| ausentes (amostra) | 50 | 50 ausências confirmadas |",
        "",
        "**O M3 errou 11 de 13** no protocolo anterior, taxa de falso positivo de 85% num "
        "estrato conferido por censo. Não era ruído do limiar de 0,95, e sim ausência das "
        "duas travas que a correção introduziu: a compatibilidade de classe (periódico com "
        "periódico, congresso com congresso) e a exclusão do trabalho acadêmico do conjunto "
        "de candidatos. Sem elas, o título do artigo casava ora com a tese homônima, ora com "
        "o artigo homônimo de outra revista. Depois da correção o M3 caiu a **um par por "
        "base**, com similaridade 0,9959, conferido por censo no segundo turno e correto nos "
        "dois casos. É a medida que sustenta manter o limiar de 0,95 como está.",
        "",
        "**Censo do estrato por título (M2 e M3), concluído em 14/07/2026.** Os dois turnos "
        "anteriores conferiram M3, tese homônima e ausentes, mas nunca o M2, que responde "
        "por 13 pares em cada base. Conferidos agora os 14 pares por título de cada base, um "
        "a um, com os dois DOI resolvidos no Crossref. **Um é falso positivo**, nas duas "
        "bases: a revisão sistemática da Cochrane *Motor neuroprosthesis for promoting "
        "recovery of function after stroke* (`10.1002/14651858.cd012991.pub2`) casou pelo "
        "título com o artigo homônimo da *Stroke* (`10.1161/strokeaha.120.029235`), que é o "
        "que o repositório de fato tem (handle 33984). São dois trabalhos distintos, e a "
        "revisão não está no repositório. O par volta a ser ausência pelo "
        "`falsos-positivos-conferencia.csv`, o que **desce** a cobertura — corrige a favor "
        "da hipótese, e por isso entra registro a registro, com o veredito do conferente, "
        "nunca por regra automática. O censo inteiro está em `censo-titulo.csv` (gerado por "
        "`src/censo_titulo.py`): 28 pares, 26 corretos e 2 reprovados, cada um com o DOI dos "
        "dois lados e o diagnóstico da divergência. Em 16 deles o repositório depositou o "
        "item **sem DOI algum**, e o título é a única via de pareamento — que é a razão de o "
        "estrato existir.",
        "",
        "**Nos outros 13 pares de cada base a divergência de DOI é do repositório, não do "
        "pareamento.** O DOI do item depositado aparece truncado (`10.1016/j.msec.2020`), "
        "sem o hífen (`jneurosci.025920.2020`), com espaço escapado "
        "(`10.1371/journal.%20pone.0230610`) e, num caso, **tomado de outro artigo**: o item "
        "32527 leva o título do artigo da *Applied Microbiology and Biotechnology* (2020) e "
        "o DOI de um artigo da *Protein Expression and Purification* (2018), o que a "
        "resolução no Crossref mostra. O par é legítimo — o artigo está lá —, mas o "
        "identificador mente. Rejeitar o par por divergência de DOI, como regra, jogaria "
        "fora o par verdadeiro junto com o falso.",
        "",
        f"**Segundo turno (99 linhas, `validacao-manual.csv`), concluído.** Confere o "
        f"protocolo corrigido. Três estratos, sorteados com semente {SEMENTE}: 2 pares da "
        "etapa M3 (censo — a correção do protocolo derrubou o M3 a um par por base), 47 "
        "registros com tese homônima e 50 ausentes, este um sorteio novo, sem sobreposição "
        "com o do primeiro turno, porque a correção mudou o conjunto de ausentes.",
        "",
        "**Procedência dos vereditos, que é diferente nos dois blocos e assim precisa ser "
        "dita no artigo.** Os 49 pares de tese homônima e de etapa M3 trazem o veredito que "
        "o autor deu no primeiro turno, sobre exatamente os mesmos pares. Os 50 do estrato "
        "dos ausentes foram julgados por **triagem automatizada, com autorização expressa do "
        "autor em 14/07/2026**, que assumiu a responsabilidade: **não** houve conferência "
        "humana item a item nesse bloco. O campo `origem_veredito` registra isso linha a "
        "linha, e a evidência de cada decisão está em `triagem-assistida.csv` e "
        "`derivacao-ausentes.csv`.",
        "",
        "**Resultado: nenhum falso negativo em 50.** Nenhum item não acadêmico de título "
        "próximo foi devolvido pela busca, e nenhum registro dado como ausente tem DOI de "
        "candidato do repositório. Teto de 6% no intervalo de confiança de 95%, pela regra "
        "de três.",
        "",
        "**Três DOIs de ausentes existem no repositório, e não são falso negativo.** Estão "
        "nos metadados de um TCC — os handles 45999 e 50701 —, que carrega o DOI do artigo "
        "de que derivou. O TCC não é candidato, de modo que o artigo segue ausente e os três "
        "registros já estão no estrato de tese homônima, conferidos. É a demonstração mais "
        "limpa do mecanismo da lacuna: o repositório guarda o DOI do artigo que não guarda.",
        "",
        "**Onde o teto de 6% de fato incide — e onde não incide.** A verificação por censo "
        "mostra que **nenhum** dos 11.084 ausentes da Scopus que têm DOI (nem dos 9.362 da "
        "WoS) carrega DOI de algum candidato do repositório. Isso não é uma segunda medida "
        "de falso negativo: é a prova de que a etapa M1 foi exaustiva, e nada mais. O que "
        "resta é o seguinte, e precisa ser dito assim na limitação do artigo.",
        "",
        "O falso negativo só pode existir onde o pareamento depende do título, isto é, "
        "quando o item está no repositório **sem DOI recuperável** e com título divergente "
        "do da base. São **3.130 dos 7.604 candidatos** que não têm DOI em nenhum campo "
        "`dc.identifier.*`, dos quais **1.651 são do tipo `article`**. É sobre esse "
        "subconjunto, e só sobre ele, que o teto de 6% se aplica. Nos registros das bases "
        "pareáveis por DOI — 98,2% do universo citável da Scopus e 96,4% do da WoS — a "
        "cobertura não depende de amostra nem de limiar de similaridade: é verificada por "
        "identidade, um a um, no censo.",
        "",
        "Examinado o trabalho acadêmico que a busca devolveu em cada um dos 50 ausentes: em "
        "6 o repositório guarda a tese ou o TCC **de onde o artigo saiu**; em 6, outro "
        "trabalho do mesmo autor; em 35, trabalho de **autor homônimo, sem relação nenhuma** "
        "(a busca por nome puxa o homônimo com facilidade — o artigo de física de partículas "
        "veio acompanhado de uma tese sobre ácido α-lipoico em ratas); em 3, nada. Em nenhum "
        "deles o artigo está no repositório. O mecanismo da lacuna se demonstra, portanto, no "
        "estrato da **tese homônima**, e não neste.",
        "",
        "A derivação, quando existe, não se decide por similaridade: o título vertido para o "
        "português tem, contra o título em inglês do artigo, a mesma similaridade de dois "
        "trabalhos sem relação (0,3 a 0,5). Ela também não altera a cobertura — a tese não é "
        "candidato, e o registro segue ausente de qualquer modo.",
        "",
    ]

    caminho = os.path.join(dados, "MATCHING.md")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    print(f"\nproveniência -> {caminho}")


def executar(dados: str) -> None:
    scopus_bruto = ler_csv(os.path.join(dados, "scopus-all.csv"))
    wos_bruto = ler_csv(os.path.join(dados, "wos-all.csv"))
    ri = ler_csv(os.path.join(dados, "ri-todos.csv"))

    scopus, fora_scopus = filtrar_universo(scopus_bruto, CITAVEIS_SCOPUS)
    wos, fora_wos = filtrar_universo(wos_bruto, CITAVEIS_WOS)
    fora_universo = {"scopus": fora_scopus, "wos": fora_wos}

    # tese, dissertação e TCC levam o título do artigo derivado: não são candidatos
    candidatos = [r for r in ri if r["type"] not in TESES_RI]
    teses = [r for r in ri if r["type"] in TESES_RI]

    print(
        f"universo citável: Scopus {len(scopus)}/{len(scopus_bruto)}, "
        f"WoS {len(wos)}/{len(wos_bruto)}"
    )
    print(f"candidatos: RI {len(candidatos)} (excluídas {len(teses)} teses/dissertações/TCC)")

    indice_ri = Indice(candidatos)
    indice_teses = Indice(teses)
    indice_wos = Indice(wos, CLASSE_BASE)  # cotejo entre bases: vocabulário de tipo é o delas
    resumos: list[dict] = []
    todos_m3: list[dict] = []
    todas_teses: list[dict] = []
    todos_ausentes: list[dict] = []
    tipos_alvo: collections.Counter = collections.Counter()
    teses_homonimas: collections.Counter = collections.Counter()
    fora_do_recorte = 0

    cotejos = [
        ("scopus-ri", "scopus", scopus, indice_ri, "match-scopus-ri.csv", "ausentes-scopus.csv"),
        ("wos-ri", "wos", wos, indice_ri, "match-wos-ri.csv", "ausentes-wos.csv"),
        ("scopus-wos", "scopus", scopus, indice_wos, "match-scopus-wos.csv", None),
    ]

    correcoes = ler_correcoes(dados)
    falsos = ler_falsos_positivos(dados)
    por_handle = {r.get("handle", ""): r for r in ri if r.get("handle")}
    universo = {r["source_id"]: r for r in scopus + wos}
    if correcoes:
        print(f"correções da conferência: {len(correcoes)} registro(s) confirmados no RI")
    if falsos:
        print(f"falsos positivos da conferência: {len(falsos)} par(es) devolvidos a ausente")

    for cotejo, fonte, base, indice, saida_pares, saida_ausentes in cotejos:
        pares, ausentes = parear(base, indice, fonte)
        if saida_ausentes:  # só o cotejo contra o repositório tem conferência
            pares, ausentes = aplicar_correcoes(pares, ausentes, fonte, correcoes, por_handle)
            pares, ausentes = aplicar_falsos_positivos(pares, ausentes, fonte, falsos, universo)
        escrever_csv(os.path.join(dados, saida_pares), pares, CAMPOS_PAR)
        if saida_ausentes:  # os dois cotejos contra o repositório, não o de bases entre si
            escrever_csv(os.path.join(dados, saida_ausentes), ausentes, CAMPOS)
            todos_m3 += [p for p in pares if p["etapa"] == "M3"]
            for a in ausentes:
                todos_ausentes.append({**a, "fonte": fonte})
            tipos_alvo.update(p["tipo_alvo"] for p in pares)
            fora_do_recorte += sum(
                1 for p in pares if not 2020 <= ano_de({"year": p["ano_alvo"]}) <= 2025
            )
            # diagnóstico: o registro ausente tem tese homônima no repositório?
            homonimas, _ = parear(ausentes, indice_teses, fonte)
            escrever_csv(
                os.path.join(dados, f"tese-homonima-{fonte}.csv"), homonimas, CAMPOS_PAR
            )
            teses_homonimas[cotejo] = len(homonimas)
            todas_teses += homonimas

        alvos = collections.Counter(p["id_alvo"] for p in pares)
        resumos.append(
            {
                "cotejo": cotejo,
                "universo": len(base),
                "etapas": collections.Counter({"M1": 0, "M2": 0, "M3": 0, "C": 0})
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

    # os ausentes com tese homônima já têm estrato próprio; o estrato "ausente" sorteia
    # dos demais, para não conferir duas vezes o mesmo registro
    com_tese = {p["id_base"] for p in todas_teses}
    ausentes_puros = [a for a in todos_ausentes if a["source_id"] not in com_tese]

    validacao = amostrar(todos_m3, todas_teses, ausentes_puros, random.Random(SEMENTE))
    caminho_validacao = os.path.join(dados, "validacao-manual.csv")
    conferido = False
    if os.path.exists(caminho_validacao):
        anterior = ler_csv(caminho_validacao)
        conferido = any(linha.get("veredito", "").strip() for linha in anterior)
    if conferido:
        # a conferência já foi feita sobre esta amostra: regravá-la apagaria o veredito
        # do pesquisador. O resto do relatório é recalculado normalmente.
        print(f"AVISO: {caminho_validacao} tem veredito preenchido; a amostra não foi regravada.")
    else:
        with open(caminho_validacao, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS_VALIDACAO)
            w.writeheader()
            w.writerows(validacao)
        print(f"{len(validacao)} linhas para conferência manual -> {caminho_validacao}")

    relatar(
        dados,
        resumos,
        indice_ri,
        len(teses),
        fora_universo,
        teses_homonimas,
        tipos_alvo,
        fora_do_recorte,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com os CSVs consolidados")
    a = p.parse_args()
    executar(a.dados)
