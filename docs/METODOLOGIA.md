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
- Filtro de data por ano, `f.dateIssued=[2020 TO 2020],equals`, um CSV por ano, no mesmo formato das duas bases.
- O repositório é baixado **por inteiro**, de 1964 a 2026, e não apenas no recorte de 2020 a 2025. O recorte delimita o universo *medido*, que é o das bases; os *candidatos* do pareamento são todos os itens do repositório (54.450), porque o artigo publicado dentro do recorte e depositado com data divergente está lá, e contá-lo como ausente superestimaria a defasagem justamente na direção da hipótese do estudo. Medido: 49 pares têm o item do repositório depositado fora da janela.
- Os itens são baixados uma vez e o pareamento roda localmente, o que evita milhares de requisições e o erro do motor de indexação sobreposto ao erro que se quer medir.

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

**DOI truncado**: descarta-se o valor que termine no prefixo do editor, sem sufixo (`10.1590/`), que algumas citações do repositório trazem incompleto e casaria com qualquer artigo do mesmo editor.

## 3. Universo medido e conjunto de candidatos

São recortes distintos, e confundi-los produz viés.

**Universo medido** — os registros das bases no período, restritos aos **documentos citáveis**: artigo, revisão, trabalho de congresso, capítulo de livro e data paper. Ficam de fora errata, editorial, carta, nota, resumo de congresso e registro retratado. Não são o produto que o repositório deposita e, por levarem o título do artigo a que se referem, casavam com o artigo homônimo já depositado e produziam par falso. Restam 12.209 dos 12.585 registros da Scopus e 10.571 dos 11.114 da Web of Science.

**Candidatos** — os itens do repositório de qualquer ano, **menos** teses, dissertações e trabalhos de conclusão (46.846 dos 54.450 itens), restando 7.604 candidatos. A exclusão não é de conveniência: na UFRN o trabalho acadêmico costuma levar o mesmo título do artigo dele derivado, muitas vezes redigido em inglês, e parte dos trabalhos de conclusão traz nos metadados o próprio DOI do artigo publicado. Aceitá-lo como par afirmaria que o artigo está no repositório quando o que está depositado é a tese. O registro cuja única correspondência é uma tese homônima é contado como **ausente**, e reportado à parte, porque é o mecanismo da lacuna que o estudo descreve: o fluxo de depósito captura o que é obrigatório e não captura o artigo que dali sai.

A regra tem erro medido: dos 50 casos conferidos, 1 era artigo publicado depositado com `dc.type` de tese (arquivo em layout de editora, na coleção de trabalhos de conclusão). Ela subestima a cobertura em cerca de 2% desses casos, e não a infla.

## 4. Etapas de pareamento

Aplicadas em ordem, sem sobreposição. Um registro pareado em uma etapa não é reavaliado nas seguintes.

| Etapa | Chave | Critério | Tratamento |
|---|---|---|---|
| M1 | DOI normalizado | igualdade exata | aceito, sem restrição de ano ou classe |
| M2 | título normalizado, ano e classe | título idêntico, diferença de ano menor ou igual a 1 e classe compatível | aceito |
| M3 | título por similaridade, ano e classe | similaridade maior ou igual a 0,95, diferença de ano menor ou igual a 1 e classe compatível | conferido item a item |
| sem match | nenhuma | nenhuma etapa casou | classificado como ausente do RI |

A tolerância de um ano acomoda a divergência entre a data de publicação online-first, registrada nas bases, e a data do fascículo, registrada no RI.

**Classe de documento** (periódico, congresso, livro): as etapas por título exigem que a classe do registro da base e a do item do repositório sejam compatíveis. O trabalho apresentado em congresso leva o mesmo título do artigo de periódico que dele resulta: sem essa trava, três registros do CLEO 2021 pareavam com o artigo homônimo publicado na *Nature Communications* e depositado no repositório, afirmando a presença de um documento que não está lá. Classe desconhecida de um dos lados não desqualifica o par — metadado faltante do repositório não pode virar ausência do artigo. O M1 não sofre a restrição: o DOI é prova de identidade.

**Cardinalidade**: cada registro da base fica com um item do repositório, e o mesmo item pode ser reclamado por mais de um registro, o que ocorre quando há depósito duplicado no repositório ou quando a base traz o mesmo trabalho duas vezes. Impedir o reuso tornaria o resultado dependente da ordem de leitura dos arquivos.

## 5. Validação manual

A conferência é do pesquisador, item a item, abrindo o registro da base ao lado do handle do repositório. Três estratos, até 50 linhas cada, sorteados com semente fixa:

- **pares da etapa M3**, ou todos, se forem menos de 50. Mede o falso positivo do limiar de similaridade.
- **registros com tese homônima no repositório**, que o protocolo classificou como ausentes. Mede o erro da regra que exclui o trabalho acadêmico do conjunto de candidatos, isto é, o artigo que foi depositado com `dc.type` de tese e que assim se perde.
- **registros classificados como ausentes**, buscados no repositório pelo DOI e pelo título. Estima o falso negativo do protocolo, tipicamente o item de título traduzido ou subtítulo divergente. A taxa entra no artigo como margem de erro da cobertura.

O primeiro turno de conferência (113 linhas) validou o protocolo anterior e motivou as três correções acima: o filtro de documentos citáveis, a exclusão das teses do conjunto de candidatos e a compatibilidade de classe nas etapas por título. Resultado: nenhum falso negativo em 50 ausentes, o que põe o teto do intervalo de confiança de 95% em 6% pela regra de três.

## 6. Métricas

Sendo `S` o conjunto de registros citáveis da Scopus, `W` o da Web of Science e `R` o de candidatos do RI:

| Métrica | Fórmula |
|---|---|
| Cobertura Scopus | `\|S∩R\| / \|S\|` |
| Cobertura Web of Science | `\|W∩R\| / \|W\|` |
| Cobertura unificada | `\|(S∪W)∩R\| / \|S∪W\|` |
| Defasagem | `1 − cobertura` |
| Sobreposição entre bases | `\|S∩W\| / \|S∪W\|` (índice de Jaccard) |

Todas calculadas para o período inteiro e por ano de publicação, além de desagregadas por tipo de documento, com os vocabulários de tipo das três fontes harmonizados por uma tabela de correspondência.

## 7. Reprodução

O leitor com credenciais próprias de API reproduz a análise executando os scripts na ordem descrita no [README](../README.md). Os dados coletados não são redistribuídos neste repositório, por restrição dos termos de uso da Elsevier e da Clarivate. A data da coleta original e os totais retornados por fonte e por ano constam da seção de metodologia do artigo, o que permite verificar a diferença esperada em uma nova execução, já que as bases e o repositório são dinâmicos.
