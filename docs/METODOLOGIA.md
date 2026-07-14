# Protocolo metodológico

Documento de referência do artigo. Registra as queries exatas, as regras de normalização e as etapas de pareamento implementadas em `src/`. O artigo apresenta o protocolo em forma condensada e remete a este documento para o detalhe operacional.

## 1. Fontes e queries

### 1.1 Scopus (Scopus Search API)

- Endpoint `https://api.elsevier.com/content/search/scopus`
- Autenticação por header `X-ELS-APIKey`, a partir de rede institucional autorizada.
- View `STANDARD`, `count=25`, paginação por deslocamento (`start`).
- Query, repetida para cada ano de 2020 a 2025:

```
AF-ID(60023857) AND PUBYEAR IS 2020
```

`AF-ID 60023857` é o identificador de afiliação da UFRN na Scopus.

A paginação não usa o parâmetro `cursor`, embora ele seja o recomendado para conjuntos grandes: a chave empregada não tem direito a ele e a requisição volta com `403 ENTITLEMENTS_ERROR`. O mesmo nível de serviço limita `count` a 25. Restou paginar por deslocamento, o que é seguro neste caso porque a janela de resultados da Scopus vai até 5.000 e a maior fatia anual da UFRN tem cerca de 2.300 registros. É esta a razão técnica de a coleta ser fatiada por ano, e não executada como consulta única do período.

Campos extraídos por registro: `eid`, `prism:doi`, `dc:title`, ano (de `prism:coverDate`), `subtypeDescription`, `prism:publicationName`, `prism:issn`.

### 1.2 Web of Science (Starter API)

- Endpoint `https://api.clarivate.com/apis/wos-starter/v1/documents`
- Autenticação por header `X-ApiKey`. Base `WOS` (Core Collection).
- Paginação `page` mais `limit=50`, com intervalo de 0,25 s entre requisições (limite de 5 req/s).
- Query, repetida para cada ano de 2020 a 2025:

```
OG=(Universidade Federal do Rio Grande do Norte) AND PY=2020
```

A grafia da organização foi escolhida por teste prévio, comparando os totais devolvidos por cada forma no período completo. O nome por extenso recupera 11.271 registros e a forma abreviada `OG=(Univ Fed Rio Grande do Norte)` recupera 9.548. Delimitar a expressão entre aspas não altera o resultado do nome por extenso, que foi a variante adotada.

Uma fatia anual da Web of Science devolve o trabalho tanto no ano da publicação antecipada quanto no ano do fascículo. Somadas as seis fatias, obtêm-se 12.111 registros, dos quais 840 são repetição do mesmo identificador em duas fatias, e restam 11.271 distintos, exatamente o total que a consulta do período inteiro anuncia. A deduplicação é feita pelo identificador `uid`, e o ano de cada registro, em todas as métricas, é o do campo `source.publishYear`, nunca o da fatia em que ele foi baixado.

Campos extraídos por registro: `uid`, `identifiers.doi`, `title`, `source.publishYear`, `types`, `source.sourceTitle`, `identifiers.issn`.

### 1.3 Repositório Institucional da UFRN (DSpace REST)

- Endpoint `https://repositorio.ufrn.br/server/api/discover/search/objects`, público, sem autenticação.
- Paginação `page` (base zero) mais `size=100`, com cortesia de 2 req/s.
- Filtro de data por ano, `f.dateIssued=[2020 TO 2020],equals`, repetido de 2020 a 2025, um CSV por ano, no mesmo formato das duas bases.
- O universo de itens do RI no período é baixado uma vez e o pareamento roda localmente, o que evita milhares de requisições e falsos negativos por variação de grafia.

Campos extraídos por item: `uuid`, `handle`, DOI, `dc.title`, `dc.date.issued`, `dc.type`.

O DOI é procurado por expressão regular em todos os campos `dc.identifier.*`, e não apenas em `dc.identifier.doi`, porque o repositório o armazena de forma inconsistente. Em amostra de 500 itens do período, dos 32 itens do tipo `article`, 31 tinham DOI recuperável: 29 em `dc.identifier.doi` e os demais apenas dentro da string de `dc.identifier.citation` ou em `dc.identifier.other`. Ler somente o campo canônico perderia esses registros e superestimaria a defasagem.

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
