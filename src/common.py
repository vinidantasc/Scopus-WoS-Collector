"""Funções compartilhadas pelos coletores das três fontes.

Somente biblioteca padrão do Python 3.11+.

Convenções válidas para os três coletores:

- as respostas cruas são gravadas em ``<saida>/../raw/`` antes de qualquer
  transformação; uma página já gravada não é buscada de novo, o que torna a
  coleta resumível e a reexecução idempotente;
- os CSVs seguem o esquema unificado ``CAMPOS``, o mesmo para Scopus, Web of
  Science e repositório, de modo que o pareamento da fase seguinte leia as três
  fontes com um único leitor.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CAMPOS = ["source_id", "doi", "title", "year", "type", "venue", "issn"]
# o repositório acrescenta o handle, que é o endereço público do item e permite
# auditar à mão qualquer par produzido no pareamento
CAMPOS_RI = CAMPOS + ["handle"]

ESPERAS = (30, 60, 120)  # backoff em segundos após 429 ou 5xx
TIMEOUT = 60

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>,;]+")
_PREFIXOS_DOI = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


def carregar_chave(nome: str) -> str:
    """Lê uma chave de API de ~/.key (linhas ``NOME=valor``, com ou sem export)."""
    caminho = os.path.expanduser("~/.key")
    padrao = re.compile(rf"^(?:export\s+)?{re.escape(nome)}\s*=\s*[\"']?(.*?)[\"']?\s*$")
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            m = padrao.match(linha)
            if m and m.group(1):
                return m.group(1)
    raise SystemExit(f"{nome} não encontrada em {caminho}")


def normalizar_doi(valor: str | None) -> str:
    """Extrai e normaliza o DOI de um valor qualquer; devolve '' se não houver.

    Aceita o DOI puro, com prefixo de resolvedor, ou embutido em texto livre
    (o repositório guarda DOI dentro da string de citação em parte dos itens).
    """
    if not valor:
        return ""
    texto = str(valor).strip().lower()
    for prefixo in _PREFIXOS_DOI:
        if texto.startswith(prefixo):
            texto = texto[len(prefixo):]
    m = _DOI_RE.search(texto)
    if not m:
        return ""
    doi = m.group(0).rstrip(".,;)]")
    # revalida depois de aparar a pontuação final: o repositório tem itens em que o
    # DOI foi depositado truncado no prefixo do editor, sem sufixo (10.29327/), e o
    # que sobra da limpeza deixaria de ser um identificador
    return doi if _DOI_RE.fullmatch(doi) else ""


def get_json(url: str, params: dict, headers: dict | None = None) -> dict:
    """GET com backoff exponencial em 429 e 5xx."""
    alvo = f"{url}?{urllib.parse.urlencode(params)}"
    cabecalhos = {"Accept": "application/json", **(headers or {})}
    for tentativa in range(len(ESPERAS) + 1):
        try:
            req = urllib.request.Request(alvo, headers=cabecalhos)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or tentativa == len(ESPERAS):
                raise
            espera = ESPERAS[tentativa]
            print(f"  HTTP {e.code}; nova tentativa em {espera}s")
            time.sleep(espera)
        except (urllib.error.URLError, TimeoutError):
            if tentativa == len(ESPERAS):
                raise
            time.sleep(ESPERAS[tentativa])
    raise RuntimeError("inalcançável")


def dir_raw(saida: str) -> str:
    """dados/x.csv -> dados/raw/ (criado se não existir)."""
    caminho = os.path.join(os.path.dirname(os.path.abspath(saida)), "raw")
    os.makedirs(caminho, exist_ok=True)
    return caminho


def caminho_raw(saida: str, fonte: str, fatia: str, pagina: int) -> str:
    return os.path.join(dir_raw(saida), f"{fonte}-{fatia}-p{pagina:04d}.json")


def ler_raw(saida: str, fonte: str, fatia: str, pagina: int) -> dict | None:
    caminho = caminho_raw(saida, fonte, fatia, pagina)
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def salvar_raw(saida: str, fonte: str, fatia: str, pagina: int, payload: dict) -> None:
    with open(caminho_raw(saida, fonte, fatia, pagina), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def escrever_csv(caminho: str, linhas: list[dict], campos: list[str] | None = None) -> None:
    campos = campos or CAMPOS
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for linha in linhas:
            w.writerow({c: linha.get(c, "") for c in campos})
    print(f"{len(linhas)} registros -> {caminho}")


def ler_csv(caminho: str) -> list[dict]:
    with open(caminho, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
