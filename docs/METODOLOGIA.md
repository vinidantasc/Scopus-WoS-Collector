# Protocolo metodológico

Documento de referência do artigo. Registra as queries exatas, as regras de normalização e as etapas de pareamento implementadas em `src/`. O artigo apresenta o protocolo em forma condensada e remete a este documento para o detalhe operacional.

## 1. Fontes e queries

### 1.1 Scopus (Scopus Search API)

- Endpoint `https://api.elsevier.com/content/search/scopus`
- Autenticação por header `X-ELS-APIKey`, a partir de rede institucional autorizada.
- View `STANDARD`, `count=200`, paginação por cursor (`cursor=*`, seguindo `cursor/@next`).
- Query, repetida para cada ano de 2020 a 2025:

```
AF-ID(60023857) AND PUBYEAR IS 2020
```

`AF-ID 60023857` é o identificador de afiliação da UFRN na Scopus.

Campos extraídos por registro: `eid`, `prism:doi`, `dc:title`, ano (de `prism:coverDate`), `subtypeDescription`, `prism:publicationName`, `prism:issn`.

### 1.2 Web of Science (Starter API)

- Endpoint `https://api.clarivate.com/apis/wos-starter/v1/documents`
- Autenticação por header `X-ApiKey`. Base `WOS` (Core Collection).
- Paginação `page` mais `limit=50`, com intervalo de 0,25 s entre requisições (limite de 5 req/s).
- Query, repetida para cada ano de 2020 a 2025:

```
OG=(Universidade Federal do Rio Grande do Norte) AND PY=2020
```

A variante de grafia da organização foi escolhida por teste prévio, comparando os totais retornados por cada forma. O teste e o total de cada variante estão registrados na seção de metodologia do artigo.

Campos extraídos por registro: `uid`, `identifiers.doi`, `title`, `source.publishYear`, `types`, `source.sourceTitle`, `identifiers.issn`.

### 1.3 Repositório Institucional da UFRN (DSpace REST)

- Endpoint `https://repositorio.ufrn.br/server/api/discover/search/objects`, público, sem autenticação.
- Paginação `page` mais `size=100`, com cortesia de 2 req/s.
- O universo de itens do RI no período é baixado uma vez e o pareamento roda localmente, o que evita milhares de requisições e falsos negativos por variação de grafia.

Campos extraídos por item: `uuid`, `handle`, DOI (extraído por expressão regular de todos os campos `dc.identifier.*`, já que o RI o armazena de forma inconsistente), `dc.title`, `dc.date.issued`, `dc.type`.

## 2. Normalizações

**DOI**, chave primária de pareamento:

- caixa baixa;
- remoção dos prefixos `https://doi.org/`, `http://dx.doi.org/` e `doi:`;
- remoção de espaços e de pontuação final;
- descarte de valores que não casem com `10\.\d{4,9}/\S+`.

**Título**, chave secundária:

- caixa baixa, remoção de acentos por normalização NFKD;
- remoção de tags HTML e MathML residuais, que a Scopus às vezes entrega no título;
- remoção de pontuação e de espaços duplicados, mantendo apenas `[a-z0-9 ]`.

**Ano**: inteiro de quatro dígitos extraído do campo de data de cada fonte.

## 3. Etapas de pareamento

Aplicadas em ordem, sem sobreposição. Um registro pareado em uma etapa não é reavaliado nas seguintes.

| Etapa | Chave | Critério | Tratamento |
|---|---|---|---|
| M1 | DOI normalizado | igualdade exata | aceito |
| M2 | título normalizado mais ano | título idêntico e diferença de ano menor ou igual a 1 | aceito |
| M3 | título por similaridade mais ano | similaridade maior ou igual a 0,95 e diferença de ano menor ou igual a 1 | conferido manualmente pelo autor |
| sem match | nenhuma | nenhuma etapa casou | classificado como ausente do RI |

A tolerância de um ano acomoda a divergência entre a data de publicação online-first, registrada nas bases, e a data do fascículo, registrada no RI.

## 4. Validação manual

Duas amostras são conferidas pelo autor, item a item, abrindo o registro da base ao lado do handle do RI:

- **50 pares da etapa M3**, ou todos, se forem menos de 50. Mede a taxa de acerto do limiar de similaridade. Abaixo de 90% de acerto, o limiar sobe e a etapa é reexecutada.
- **50 registros classificados como ausentes**, buscados manualmente no RI pelo título. Estima o falso negativo do protocolo, ou seja, o item que existe no RI mas não pareou, tipicamente por título traduzido ou subtítulo divergente. A taxa estimada é reportada no artigo como margem de erro da cobertura.

## 5. Métricas

Sendo `S` o conjunto de registros da Scopus, `W` o da Web of Science e `R` o de itens do RI no período:

| Métrica | Fórmula |
|---|---|
| Cobertura Scopus | `\|S∩R\| / \|S\|` |
| Cobertura Web of Science | `\|W∩R\| / \|W\|` |
| Cobertura unificada | `\|(S∪W)∩R\| / \|S∪W\|` |
| Defasagem | `1 − cobertura` |
| Sobreposição entre bases | `\|S∩W\| / \|S∪W\|` (índice de Jaccard) |

Todas calculadas para o período inteiro e por ano de publicação, além de desagregadas por tipo de documento, com os vocabulários de tipo das três fontes harmonizados por uma tabela de correspondência.

## 6. Reprodução

O leitor com credenciais próprias de API reproduz a análise executando os scripts na ordem descrita no [README](../README.md). Os dados coletados não são redistribuídos neste repositório, por restrição dos termos de uso da Elsevier e da Clarivate. A data da coleta original e os totais retornados por fonte e por ano constam da seção de metodologia do artigo, o que permite verificar a diferença esperada em uma nova execução, já que as bases e o repositório são dinâmicos.
