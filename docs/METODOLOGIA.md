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
- O repositório é baixado **por inteiro**, de 1964 a 2026, e não apenas no recorte de 2020 a 2025. O recorte delimita o universo *medido*, que é o das bases; os *candidatos* do pareamento são todos os itens do repositório (54.450), porque o artigo publicado dentro do recorte e depositado com data divergente está lá, e contá-lo como ausente superestimaria a defasagem justamente na direção da hipótese do estudo. Medido: 48 pares têm o item do repositório depositado fora da janela.
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

A regra tem erro conhecido, medido **por censo** e **corrigido**. O estrato de tese homônima foi conferido inteiro, e não por amostra: dos 47 registros, 45 são de fato a tese homônima e 2 — o mesmo artigo, indexado nas duas bases — são o artigo publicado depositado com `dc.type` de trabalho de conclusão, o arquivo em layout de editora na coleção de TCC. Como o censo identifica um a um os registros em que a regra erra, eles não permanecem como erro residual: voltam a contar como cobertos pela etapa **C** (seção 4), a partir de `correcoes-conferencia.csv`. A correção sobe a cobertura, isto é, corrige contra a hipótese do estudo.

## 4. Etapas de pareamento

Aplicadas em ordem, sem sobreposição. Um registro pareado em uma etapa não é reavaliado nas seguintes.

| Etapa | Chave | Critério | Tratamento |
|---|---|---|---|
| M1 | DOI normalizado | igualdade exata | aceito, sem restrição de ano ou classe |
| M2 | título normalizado, ano e classe | título idêntico, diferença de ano menor ou igual a 1 e classe compatível | aceito |
| M3 | título por similaridade, ano e classe | similaridade maior ou igual a 0,95, diferença de ano menor ou igual a 1 e classe compatível | conferido item a item |
| C | conferência do pesquisador | o item do repositório é o artigo, depositado com `dc.type` de trabalho acadêmico | aceito, a partir de `correcoes-conferencia.csv` |
| F | conferência do pesquisador | o par por título une dois trabalhos distintos de mesmo título, com DOI diferente de cada lado | devolvido a ausente, a partir de `falsos-positivos-conferencia.csv` |
| sem match | nenhuma | nenhuma etapa casou | classificado como ausente do RI |

As etapas C e F são as duas faces da decisão humana no protocolo, e correm em sentidos opostos: C sobe a cobertura, F a desce. Nenhuma das duas é regra automática. Ambas se aplicam registro a registro, sobre estratos conferidos por censo, e cada registro corrigido está nomeado no CSV correspondente, com o motivo.

**A etapa F, e por que ela não vira regra.** O estrato dos pares por título tem 14 pares em cada base, e os dois primeiros turnos de conferência nunca o examinaram — conferiram M3, tese homônima e ausentes. Conferido por censo em 14/07/2026, com os dois DOI de cada par resolvidos no Crossref, o estrato tem **um falso positivo**, o mesmo nas duas bases: a revisão sistemática da Cochrane *Motor neuroprosthesis for promoting recovery of function after stroke* (`10.1002/14651858.cd012991.pub2`) casou pelo título com o artigo homônimo da *Stroke* (`10.1161/strokeaha.120.029235`), que é o que o repositório tem depositado (handle 33984). São dois trabalhos publicados, de mesmo título e mesmo ano, e a revisão não está no repositório.

O censo inteiro está em `censo-titulo.csv`, gerado por `src/censo_titulo.py`: um par por linha, com o DOI dos dois lados, o diagnóstico da divergência entre eles e o veredito. Dos 28 pares, 26 são corretos e 2 são o falso positivo. Em 16 deles o repositório depositou o item **sem DOI algum**, e o título é a única via de pareamento — que é a razão de o estrato existir.

A tentação seria transformar isso em regra: rejeitar o par por título sempre que os dois lados tiverem DOI e os DOI divergirem. **Medido, o custo dessa regra é alto e o benefício é um só par.** Nos outros 13 pares de cada base, quem diverge é o DOI **do repositório**, que está corrompido: truncado (`10.1016/j.msec.2020`), sem o hífen (`jneurosci.025920.2020`), com o espaço escapado (`10.1371/journal.%20pone.0230610`) e, num caso, tomado de outro artigo — o item 32527 leva o título do artigo da *Applied Microbiology and Biotechnology* (2020) e, no campo do DOI, o identificador de um artigo da *Protein Expression and Purification* (2018). A regra descartaria esses pares legítimos junto com o falso, e o faria na direção da hipótese do estudo. Por isso a correção é feita por censo, e não por critério automático.

A tolerância de um ano acomoda a divergência entre a data de publicação online-first, registrada nas bases, e a data do fascículo, registrada no RI.

A etapa **C** não é automática: é a decisão humana entrando no protocolo. Existe porque a regra que exclui o trabalho acadêmico dos candidatos erra num caso conhecido — o artigo depositado com o tipo errado —, e porque o estrato foi conferido por censo, o que permite identificar esse erro registro a registro em vez de deixá-lo como margem. Cada linha do arquivo de correções nomeia o registro, o handle e o motivo, e é auditável.

**Classe de documento** (periódico, congresso, livro): as etapas por título exigem que a classe do registro da base e a do item do repositório sejam compatíveis. O trabalho apresentado em congresso leva o mesmo título do artigo de periódico que dele resulta: sem essa trava, três registros do CLEO 2021 pareavam com o artigo homônimo publicado na *Nature Communications* e depositado no repositório, afirmando a presença de um documento que não está lá. Classe desconhecida de um dos lados não desqualifica o par — metadado faltante do repositório não pode virar ausência do artigo. O M1 não sofre a restrição: o DOI é prova de identidade.

**Cardinalidade**: cada registro da base fica com um item do repositório, e o mesmo item pode ser reclamado por mais de um registro, o que ocorre quando há depósito duplicado no repositório ou quando a base traz o mesmo trabalho duas vezes. Impedir o reuso tornaria o resultado dependente da ordem de leitura dos arquivos.

## 5. Validação da amostra

A conferência dos pares (etapa M3 e tese homônima) é do pesquisador, item a item, abrindo o registro da base ao lado do handle do repositório. **O estrato dos ausentes do segundo turno foi julgado por triagem automatizada**, com autorização expressa do autor, que assumiu a responsabilidade pelo resultado; a procedência de cada veredito fica registrada no campo `origem_veredito` do CSV de validação, e o dado bruto que sustentou cada decisão, em `derivacao-ausentes.csv`. Não se afirma conferência humana onde ela não houve. Três estratos, até 50 linhas cada, sorteados com semente fixa:

- **pares da etapa M3**, ou todos, se forem menos de 50. Mede o falso positivo do limiar de similaridade. No protocolo anterior, os 13 pares M3 foram conferidos por censo e **11 estavam errados** (6 casavam com a tese homônima e 5 com documento que não era o item do repositório): falso positivo de 85%. A causa não era o limiar de 0,95, e sim a ausência das duas travas que as correções acima introduziram — a compatibilidade de classe e a exclusão do trabalho acadêmico do conjunto de candidatos. Com elas, restou **um único par M3 por base**, de similaridade 0,9959: o estrato virou censo, os dois pares foram conferidos e estão corretos. A etapa M3 responde por 1 dos 910 pares da Scopus e 1 dos 833 da Web of Science, e o limiar de 0,95 fica registrado como está, sem revisão, por não ter efeito mensurável sobre a cobertura.
- **registros com tese homônima no repositório**, que o protocolo classificou como ausentes. Mede o erro da regra que exclui o trabalho acadêmico do conjunto de candidatos, isto é, o artigo que foi depositado com `dc.type` de tese e que assim se perde.
- **registros classificados como ausentes**, procurados no repositório pelos caminhos que o pareamento **não** usa. Estima o falso negativo do protocolo, tipicamente o item de título traduzido ou de subtítulo divergente. A taxa entra no artigo como margem de erro da cobertura.

O script `src/triagem.py` prepara a conferência do estrato dos ausentes: para cada registro sorteado, procura o trabalho no repositório pelo **DOI no índice de busca** (a busca Discovery varre todos os campos de metadado, inclusive os que a coleta lê por expressão regular), pelo **título como frase**, pelo **início do título** (o título inteiro entre aspas falha por qualquer divergência de pontuação) e pelo **nome do primeiro autor**, além de varrer o repositório local inteiro por similaridade de título sem limiar. A evidência de cada busca é gravada numa coluna do CSV. O script não decide: mostra o que achou, e o veredito é dado por pessoa.

Duas regras de leitura da triagem, escolhidas para não fabricar vínculo nem esconder achado:

- **Derivação não se decide por similaridade.** O trabalho de conclusão que origina o artigo costuma estar depositado com o título vertido para o português, e a similaridade entre os dois títulos fica entre 0,3 e 0,5 — abaixo de qualquer limiar defensável, no mesmo patamar de duas teses sem relação nenhuma. A tese é listada com a busca que a devolveu, e quem julga o vínculo é o conferente. A decisão não altera a cobertura: a tese não é candidato, e o registro segue ausente de qualquer modo. Ela alimenta o mecanismo da lacuna, descrito no artigo.
- **Falso negativo só pode vir de item não acadêmico.** Só nesse caso a triagem pede revisão do pareamento.

O primeiro turno (113 linhas) validou o protocolo anterior e motivou as três correções acima: dos 113 registros conferidos, 7 pares estavam corretos, 56 eram falsos positivos e 50 eram ausências confirmadas. O segundo turno (99 linhas) confere o protocolo corrigido, sobre um sorteio novo de ausentes, já que a correção mudou esse conjunto. Nos dois turnos: **nenhum falso negativo em 50 ausentes**, o que põe o teto do intervalo de confiança de 95% em 6% pela regra de três.

**O teto de 6% não incide sobre o resultado inteiro, e sim sobre uma parte dele.** Verificado por censo, nenhum dos 11.084 registros ausentes da Scopus que têm DOI (nem dos 9.362 da Web of Science) carrega DOI de algum candidato do repositório. Isso não é uma segunda estimativa de falso negativo: apenas atesta que a etapa M1 foi exaustiva. O falso negativo só pode existir onde o pareamento depende do título, isto é, quando o item está depositado **sem DOI recuperável** em nenhum campo `dc.identifier.*` e com título divergente do da base. São 3.130 dos 7.604 candidatos, 1.651 deles do tipo `article`. A margem de erro amostral pertence a esse subconjunto. Para os 98,2% do universo citável da Scopus e os 96,4% do da Web of Science que têm DOI, a presença ou ausência no repositório é decidida por identidade, um a um, e não por amostra nem por limiar de similaridade.

Examinado o trabalho acadêmico que a busca devolveu em cada um dos 50 ausentes do segundo turno, o repositório guarda a tese ou o TCC **de onde o artigo saiu** em 6 casos, outro trabalho do mesmo autor em 6, e trabalho de **autor homônimo, sem relação nenhuma**, em 35 — a busca por nome puxa o homônimo com facilidade, e tomá-lo por trabalho do autor inflaria o achado. O mecanismo da lacuna, portanto, se demonstra no estrato da **tese homônima**, onde 45 pares conferidos pelo autor são o trabalho acadêmico ocupando o lugar do artigo, e não neste.

**Reedição conta como publicação distinta.** A tolerância de um ano entre a data da base e a do depósito acomoda a publicação antecipada, mas não a reedição: o capítulo *Theta-Gamma Cross-Frequency Analyses (Hippocampus)* está no repositório na primeira edição da *Encyclopedia of Computational Neuroscience* (2018, `10.1007/978-1-4614-7320-6_100658-1`) e é indexado pela Scopus na segunda (2022, `10.1007/978-1-0716-1006-0_100658`). O título é o mesmo, os DOI não. O registro da segunda edição é contado como **ausente**, porque DOI distinto é publicação distinta, e a segunda edição de fato não está depositada. É o único caso do gênero no universo medido, e não altera o resultado na casa decimal.

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

**A união das bases se conta em trabalhos, não em registros.** Scopus e Web of Science identificam o mesmo trabalho com identificadores próprios, e o cotejo entre as duas é o que dá a correspondência. Somar os universos e subtrair os pares parece bastar e não basta: em 14 casos, duas entradas da Scopus apontam para o mesmo registro da WoS, isto é, o trabalho está duplicado numa das bases. `metricas.py` monta um grafo de identidade em que os nós são os registros das três fontes e as arestas são os pares produzidos no pareamento; cada componente conexo é um trabalho. É desse grafo que saem, de uma vez, a união (13.387 trabalhos), a sobreposição das bases e as sete regiões do diagrama de Venn — que de outro modo teriam de ser contadas por caminhos distintos, com três oportunidades de divergir. Um trabalho da união conta como coberto se **qualquer** dos registros que o representam parear com o repositório; exigir que os dois pareiem mediria o pareamento, e não a presença.

**A harmonização dos tipos agrega por família.** O tipo da Web of Science é composto (`Article; Early Access`, `Article; Data Paper`), e a família é o primeiro componente que se reconhece — a mesma agregação usada na composição do universo. Onde a base não declara tipo algum de uma família, a tabela traz um traço, e não zero por cento: universo vazio não é cobertura nula.

**Ano de publicação e ano de depósito são coisas distintas, e a distinção é o que explica a série temporal.** A cobertura por ano de publicação não decresce de forma monótona: cai de 2020 a 2024 e sobe de novo em 2025, o oposto do que se esperaria de um repositório alimentado por depósito corrente, em que o ano mais recente teria a menor cobertura por efeito do atraso de depósito. `deposito.py` recupera a data de depósito (`dc.date.accessioned`) das respostas já gravadas em `data/raw/`, sem requisição nova, e o cruzamento com o ano de publicação mostra que o repique vem de uma carga concentrada de depósitos, e não do fluxo corrente. Sem esse cruzamento, a interpretação da série seria conjectura.

## 7. Reprodução

O leitor com credenciais próprias de API reproduz a análise executando os scripts na ordem descrita no [README](../README.md). Os dados coletados não são redistribuídos neste repositório, por restrição dos termos de uso da Elsevier e da Clarivate. A data da coleta original e os totais retornados por fonte e por ano constam da seção de metodologia do artigo, o que permite verificar a diferença esperada em uma nova execução, já que as bases e o repositório são dinâmicos.
