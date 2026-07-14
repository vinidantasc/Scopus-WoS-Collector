# Scopus-WoS-Collector

Código de coleta e análise usado no artigo **"Defasagem de cobertura do Repositório Institucional da UFRN em relação às bases Scopus e Web of Science (2020-2025)"** (Vinicius Carvalho, PPGCI/UFRN).

O repositório existe para tornar o procedimento metodológico do artigo reprodutível sem imprimir centenas de linhas de código no texto. O artigo descreve o que cada etapa faz e remete a este endereço para o código exato que a executa.

## O que este código faz

Mede a cobertura do Repositório Institucional da UFRN (repositorio.ufrn.br, DSpace 7) frente à produção científica da instituição indexada na Scopus e na Web of Science entre 2020 e 2025. Em três etapas:

1. **Coleta.** Consulta as três APIs (Scopus Search, Web of Science Starter e DSpace REST), fatiando por ano de publicação, e grava um CSV por fonte e ano.
2. **Pareamento.** Para cada registro citável das bases, procura o item correspondente no RI por DOI normalizado, depois por título normalizado mais ano, depois por similaridade de título — estas duas últimas restritas a itens de classe compatível (periódico com periódico, congresso com congresso). Tese, dissertação e trabalho de conclusão não entram como candidatos: levam o título do artigo que deles deriva, e por vezes o próprio DOI, de modo que aceitá-los afirmaria a presença do artigo onde só está o trabalho acadêmico. Produz os conjuntos de cobertos, de ausentes e de registros cuja única correspondência é uma tese homônima.
3. **Métricas e figuras.** Calcula cobertura global, por ano de publicação, por tipo de documento e por exclusividade de base, além da sobreposição entre as bases, e gera as figuras do artigo. A união das bases é contada em **trabalhos**, não em registros: Scopus e WoS identificam o mesmo trabalho de modos próprios, e o cotejo entre elas dá a correspondência. `deposito.py` recupera das respostas já coletadas a data de depósito de cada item do repositório (`dc.date.accessioned`), que é o que distingue a cobertura de um ano de publicação do momento em que o depósito ocorreu.

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

Os três coletores têm a mesma interface, um ano por execução e um CSV por ano. As duas bases são coletadas **no recorte do estudo**; o repositório é coletado **por inteiro**:

```bash
# bases: só o recorte medido
for ano in 2020 2021 2022 2023 2024 2025; do
  python3 src/coleta_scopus.py --ano $ano --saida data/scopus-$ano.csv
  python3 src/coleta_wos.py    --ano $ano --saida data/wos-$ano.csv
done

# repositório: todos os anos, porque os candidatos do pareamento não são o recorte
python3 src/coleta_ri.py --de 1964 --ate 2026 --dados data/

python3 src/consolida.py --dados data/ --de 2020 --ate 2025
python3 src/matching.py  --dados data/
python3 src/deposito.py  --dados data/
python3 src/metricas.py  --dados data/
python3 src/figuras.py   --dados data/ --saida figuras/
```

Coletar o repositório apenas no recorte parece economia e é erro: `matching.py` monta os candidatos a partir de `ri-todos.csv`, e o artigo publicado no recorte mas depositado com data divergente seria contado como ausente, o que superestima a defasagem na direção da hipótese do estudo.

`consolida.py` junta as fatias anuais de cada fonte, remove duplicatas e imprime, em Markdown, os totais que a metodologia do artigo declara.

Cada script de coleta grava a resposta bruta em `data/raw/` antes de transformar. Uma página já gravada não é buscada de novo, de modo que a coleta retoma de onde parou depois de um erro de quota e a reexecução não duplica saída. Para forçar nova busca, use `--refazer`.

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
