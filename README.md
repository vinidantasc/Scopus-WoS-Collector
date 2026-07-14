# Scopus-WoS-Collector

Código de coleta e análise usado no artigo **"Defasagem de cobertura do Repositório Institucional da UFRN em relação às bases Scopus e Web of Science (2020-2025)"** (Vinicius Carvalho, PPGCI/UFRN).

O repositório existe para tornar o procedimento metodológico do artigo reprodutível sem imprimir centenas de linhas de código no texto. O artigo descreve o que cada etapa faz e remete a este endereço para o código exato que a executa.

## O que este código faz

Mede a cobertura do Repositório Institucional da UFRN (repositorio.ufrn.br, DSpace 7) frente à produção científica da instituição indexada na Scopus e na Web of Science entre 2020 e 2025. Em três etapas:

1. **Coleta.** Consulta as três APIs (Scopus Search, Web of Science Starter e DSpace REST), fatiando por ano de publicação, e grava um CSV por fonte e ano.
2. **Pareamento.** Para cada registro das bases, procura o item correspondente no RI por DOI normalizado, depois por título normalizado mais ano, depois por similaridade de título. Produz os conjuntos de cobertos e de ausentes.
3. **Métricas e figuras.** Calcula cobertura global, por ano e por tipo de documento, além da sobreposição entre as bases, e gera as figuras do artigo.

## Escopo do que está publicado aqui

Este repositório contém **apenas o código e a documentação do procedimento**. Não distribui os metadados coletados nas bases, porque os termos de uso da Elsevier e da Clarivate restringem a redistribuição em massa de registros. Quem quiser reproduzir os números do artigo executa os scripts com as próprias credenciais de API, e as saídas são geradas localmente em `data/`, que está no `.gitignore`.

Os resultados agregados (coberturas, totais por ano e por tipo) estão nas tabelas do artigo.

## Requisitos

- Python 3.11 ou superior.
- Chave da **Scopus Search API** (Elsevier), com acesso a partir de rede institucional autorizada.
- Chave da **Web of Science Starter API** (Clarivate).
- Nenhuma credencial para o RI da UFRN, cuja API REST é pública e de leitura anônima.

As chaves são lidas de variáveis de ambiente:

```bash
export API_KEY_SCOPUS="sua-chave-elsevier"
export API_KEY_WOS="sua-chave-clarivate"
```

Dependências de execução da coleta e do pareamento: biblioteca padrão do Python. As figuras usam `matplotlib` e `matplotlib-venn` (ver `requirements.txt`).

## Uso

```bash
python3 src/coleta_scopus.py --ano 2020 --saida data/scopus-2020.csv
python3 src/coleta_wos.py    --ano 2020 --saida data/wos-2020.csv
python3 src/coleta_ri.py     --de 2020 --ate 2025 --saida data/ri-2020-2025.csv
python3 src/consolida.py     --entrada data/ --saida data/
python3 src/matching.py      --bases data/ --ri data/ri-2020-2025.csv --saida data/
python3 src/metricas.py      --entrada data/ --saida data/metricas.csv
python3 src/figuras.py       --entrada data/metricas.csv --saida figuras/
```

Cada script de coleta salva a resposta bruta antes de transformar, é reexecutável sem duplicar saída e retoma da última página em caso de erro de quota.

## Estrutura

```
src/          scripts de coleta, pareamento, métricas e figuras
docs/         protocolo metodológico detalhado (queries exatas, regras de normalização, etapas de pareamento)
data/         saídas locais da execução (ignorado pelo git)
figuras/      figuras geradas (ignorado pelo git)
```

## Estado

Em desenvolvimento. Os scripts são adicionados conforme cada etapa do artigo é executada. A versão citada no artigo será marcada com uma tag e depositada no Zenodo para receber DOI.

## Licença

MIT, ver [LICENSE](LICENSE).
