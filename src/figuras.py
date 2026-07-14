"""Fase 3 — figuras do artigo, geradas a partir das métricas.

    python3 src/figuras.py --dados /caminho/dados --saida /caminho/figuras

Lê ``dados/metricas.csv`` e desenha as três figuras que saem de cálculo:

    fig2  diagrama de Venn: Scopus, Web of Science e repositório
    fig3  série temporal da cobertura, 2020–2025
    fig4  cobertura por tipo de documento

As figuras **não recalculam nada**. Todo número vem do CSV que ``src/metricas.py``
gravou, de modo que figura e tabela não podem divergir: o que se lê no eixo é o que está
na tabela, e uma correção nas métricas propaga para as duas.

A figura 1, o fluxograma do procedimento, não sai de dado e é desenhada à parte.

Saída em PNG (300 dpi, para a submissão) e SVG (vetorial, para a diagramação). Escala de
cinza: o periódico é impresso, e a distinção entre as séries não pode depender de cor.

Exige matplotlib e matplotlib-venn (ver requirements.txt).
"""

from __future__ import annotations

import argparse
import csv
import os

import matplotlib

matplotlib.use("Agg")  # sem servidor gráfico: o script roda em terminal
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib_venn import venn3  # noqa: E402

ANOS = [2020, 2021, 2022, 2023, 2024, 2025]
ORDEM_TIPOS = ["artigo", "revisão", "trabalho de congresso", "capítulo de livro", "data paper"]

CINZAS = {"scopus": "0.25", "wos": "0.55", "uniao": "0.05"}
MARCADORES = {"scopus": "o", "wos": "s", "uniao": "^"}
NOMES = {"scopus": "Scopus", "wos": "Web of Science", "uniao": "união das bases"}

DPI = 300  # exigência corrente de periódico impresso


def milhar(n: int) -> str:
    """12209 -> 12.209, na convenção brasileira."""
    return f"{n:,}".replace(",", ".")


def porcento(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}%".replace(".", ",")


def ler_metricas(dados: str) -> dict[tuple[str, str, str], str]:
    """metricas.csv em memória, indexado por (métrica, recorte, chave)."""
    caminho = os.path.join(dados, "metricas.csv")
    if not os.path.exists(caminho):
        raise SystemExit("metricas.csv não existe; rode antes: python3 src/metricas.py --dados …")
    with open(caminho, encoding="utf-8", newline="") as f:
        return {(l["metrica"], l["recorte"], l["chave"]): l["valor"] for l in csv.DictReader(f)}


def salvar(fig: plt.Figure, saida: str, nome: str) -> None:
    os.makedirs(saida, exist_ok=True)
    for formato in ("png", "svg"):
        caminho = os.path.join(saida, f"{nome}.{formato}")
        fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor="white")
        print(f"figura -> {caminho}")
    plt.close(fig)


def figura_venn(metricas: dict, saida: str) -> None:
    """Fig. 2 — as sete regiões, em trabalhos.

    O repositório entra com os candidatos ao pareamento (sem tese, dissertação e trabalho
    de conclusão), que é o conjunto contra o qual a fase 2 pareou. A região do repositório
    sozinho é grande e não é lacuna das bases: é o que o repositório guarda e as bases não
    indexam. O que o artigo mede são as três regiões de interseção, que são pequenas.
    """
    regiao = lambda r: int(metricas[("regiao_venn", "obras", r)])  # noqa: E731
    fig, eixo = plt.subplots(figsize=(7, 5.5))
    diagrama = venn3(
        subsets=(
            regiao("scopus"),
            regiao("wos"),
            regiao("scopus+wos"),
            regiao("ri"),
            regiao("scopus+ri"),
            regiao("wos+ri"),
            regiao("scopus+wos+ri"),
        ),
        set_labels=("Scopus", "Web of Science", "Repositório Institucional"),
        set_colors=("0.35", "0.65", "0.85"),
        alpha=0.7,
        ax=eixo,
    )
    for rotulo in diagrama.subset_labels:
        if rotulo:
            rotulo.set_text(milhar(int(rotulo.get_text())))
            rotulo.set_fontsize(9)
    for rotulo in diagrama.set_labels:
        if rotulo:
            rotulo.set_fontsize(10)
    eixo.set_title(
        "Trabalhos indexados e depositados, 2020–2025\n"
        "(repositório: itens elegíveis ao pareamento, de qualquer ano)",
        fontsize=11,
    )
    salvar(fig, saida, "fig2-venn")


def figura_serie(metricas: dict, saida: str) -> None:
    """Fig. 3 — cobertura anual.

    A série não decresce de forma monótona: cai de 2020 a 2024 e sobe em 2025. O padrão não
    é o de um repositório alimentado por depósito corrente, e a tabela 3 do relatório
    (ano de depósito × ano de publicação) é que o explica.
    """
    fig, eixo = plt.subplots(figsize=(7, 4.5))
    for recorte in ("scopus", "wos", "uniao"):
        valores = [float(metricas[("cobertura_pct", recorte, str(a))]) for a in ANOS]
        eixo.plot(
            ANOS,
            valores,
            marker=MARCADORES[recorte],
            color=CINZAS[recorte],
            linewidth=1.4,
            markersize=5,
            label=NOMES[recorte],
        )
        if recorte != "uniao":
            continue
        # só a união recebe rótulo: é a linha que o texto do artigo cita, e rotular as três
        # empilharia número sobre marcador nos anos em que as séries se cruzam
        for ano, valor in zip(ANOS, valores):
            eixo.annotate(
                porcento(valor),
                (ano, valor),
                textcoords="offset points",
                xytext=(0, -18),
                ha="center",
                va="center",
                fontsize=8,
                color="0.25",
            )
    eixo.set_xlabel("ano de publicação")
    eixo.set_ylabel("cobertura do repositório (%)")
    eixo.set_ylim(0, 16)
    eixo.set_xticks(ANOS)
    eixo.grid(axis="y", linestyle=":", linewidth=0.6, color="0.8")
    eixo.spines["top"].set_visible(False)
    eixo.spines["right"].set_visible(False)
    eixo.legend(frameon=False, fontsize=9)
    salvar(fig, saida, "fig3-serie")


def figura_tipos(metricas: dict, saida: str) -> None:
    """Fig. 4 — cobertura por tipo de documento.

    O tipo em que o repositório mais cobre é aquele que seu fluxo de depósito de fato
    captura. Trabalho de congresso e capítulo de livro ficam em torno de zero, e a barra
    ausente da WoS não é cobertura nula: é tipo que a base não declara no recorte.
    """
    tipos = [
        t for t in ORDEM_TIPOS
        if ("cobertura_tipo_pct", "scopus", t) in metricas
        or ("cobertura_tipo_pct", "wos", t) in metricas
    ]
    largura = 0.42
    separacao = 0.5  # entre as duas barras do mesmo tipo: o rótulo traz a fração e é largo
    # figura larga: o rótulo traz a fração, e as duas séries do mesmo tipo ficam lado a lado
    fig, eixo = plt.subplots(figsize=(9.5, 4.6))
    for i, recorte in enumerate(("scopus", "wos")):
        posicoes = [x + (i - 0.5) * separacao for x in range(len(tipos))]
        valores = [float(metricas.get(("cobertura_tipo_pct", recorte, t), 0)) for t in tipos]
        universos = [int(metricas.get(("universo_tipo", recorte, t), 0)) for t in tipos]
        cobertos = [int(metricas.get(("cobertos_tipo", recorte, t), 0)) for t in tipos]
        barras = eixo.bar(
            posicoes,
            valores,
            largura,
            color=CINZAS[recorte],
            edgecolor="black",
            linewidth=0.5,
            label=NOMES[recorte],
        )
        # o percentual sozinho engana onde o universo é pequeno: o data paper tem 5,9% de
        # cobertura, que é 1 registro em 17. A fração vai junto, sempre
        for barra, valor, c, u in zip(barras, valores, cobertos, universos):
            texto = f"{porcento(valor)}\n{milhar(c)}/{milhar(u)}" if u else "—"
            eixo.annotate(
                texto,
                (barra.get_x() + barra.get_width() / 2, valor),
                textcoords="offset points",
                xytext=(0, 3),
                ha="center",
                fontsize=7.5,
                linespacing=1.3,
            )
    eixo.set_xticks(range(len(tipos)))
    eixo.set_xticklabels([t.replace(" de ", "\nde ") for t in tipos], fontsize=9)
    eixo.set_ylabel("cobertura do repositório (%)")
    eixo.set_ylim(0, 13)
    eixo.grid(axis="y", linestyle=":", linewidth=0.6, color="0.8")
    eixo.set_axisbelow(True)
    eixo.spines["top"].set_visible(False)
    eixo.spines["right"].set_visible(False)
    eixo.legend(frameon=False, fontsize=9)
    salvar(fig, saida, "fig4-tipos")


def executar(dados: str, saida: str) -> None:
    metricas = ler_metricas(dados)
    plt.rcParams.update({"font.family": "serif", "font.size": 10})
    figura_venn(metricas, saida)
    figura_serie(metricas, saida)
    figura_tipos(metricas, saida)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dados", required=True, help="diretório com metricas.csv")
    p.add_argument("--saida", required=True, help="diretório onde gravar as figuras")
    a = p.parse_args()
    executar(a.dados, a.saida)
