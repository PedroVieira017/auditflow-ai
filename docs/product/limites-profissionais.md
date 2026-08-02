# Limites profissionais e responsabilidade

## Decisão de posicionamento

O AuditFlow AI é uma plataforma de preparação, monitorização e documentação de
testes de controlo. Serve equipas financeiras, responsáveis de controlo,
auditores internos e profissionais de auditoria, incluindo ROC e SROC.

O produto não é um ROC, não presta por si só serviços de auditoria às contas e
não transforma automaticamente resultados técnicos em conclusões profissionais.

## Atos que o produto não pratica

Em Portugal, a auditoria às contas exercida segundo as normas de auditoria em
vigor é uma função de interesse público reservada a ROC e SROC. Inclui a revisão
legal das contas, a revisão voluntária das contas e os serviços relacionados
abrangidos pelo Estatuto da OROC.

Por isso, o AuditFlow AI não deve:

- emitir uma certificação legal das contas;
- emitir um relatório de revisão voluntária das contas;
- apresentar uma opinião de auditoria;
- declarar que as contas apresentam uma imagem verdadeira e apropriada;
- declarar automaticamente que um controlo é adequado ou eficaz;
- usar a assinatura de um ROC como validação automática de um relatório gerado.

Mesmo quando um ROC utiliza a plataforma, a sua assinatura não é um simples
carimbo sobre o resultado do software. O profissional continua responsável por
aceitar e planear o trabalho, manter a independência aplicável, executar ou
supervisionar os procedimentos necessários, obter prova suficiente, documentar
o julgamento e emitir o relatório previsto nas normas e na lei.

## O que o produto pode fazer

Sem emitir uma opinião profissional, a plataforma pode:

- receber, validar e normalizar dados fornecidos pelo cliente;
- executar testes objetivos e regras configuradas;
- identificar exceções aos critérios definidos;
- mostrar os dados e documentos que originaram cada resultado;
- manter o histórico das regras, execuções, decisões e evidências;
- apoiar a investigação e o acompanhamento de medidas corretivas;
- preparar um dossier de trabalho ou um rascunho claramente identificado;
- entregar a informação a uma pessoa competente para revisão e conclusão.

Um alerta significa apenas que os dados satisfazem os critérios de uma regra.
Não prova fraude, erro material, incumprimento legal ou deficiência de controlo.

## Como nasce um controlo

Os controlos variam entre empresas, mas não nascem apenas dos KPIs. O modelo de
configuração deve seguir esta sequência:

1. objetivos da organização e obrigações legais ou contratuais;
2. cenários de risco que podem impedir esses objetivos;
3. controlos preventivos, detetivos ou corretivos;
4. responsáveis, frequência e evidência esperada de cada controlo;
5. testes, regras e limites usados para monitorizar a sua execução;
6. indicadores e alertas;
7. investigação e conclusão humana.

Um KPI mede sobretudo desempenho, um KRI acompanha exposição ao risco e um
indicador de controlo acompanha a execução ou eficácia de um controlo. Podem
estar relacionados, mas não são equivalentes.

Exemplo:

- objetivo: pagar apenas faturas válidas uma única vez;
- risco: duplicação de uma obrigação ou pagamento;
- controlo: validação de unicidade antes da autorização;
- evidência: fatura, fornecedor, aprovação e referência do pagamento;
- teste: procurar combinações repetidas de fornecedor, número, data, valor e
  moeda;
- alerta: duas ou mais linhas satisfazem a combinação;
- conclusão: uma pessoa confirma se existe duplicação real e decide a ação.

## Configuração por empresa

Cada organização deve possuir um perfil de controlo próprio e versionado, com:

- objetivos, riscos e critérios aprovados pela organização;
- regras ativadas e respetivos parâmetros;
- origem de cada regra: interna, contratual, regulamentar ou modelo sugerido;
- pessoa que aprovou a configuração e data de entrada em vigor;
- histórico imutável das versões usadas em cada execução;
- responsáveis pela análise e conclusão dos alertas.

Modelos setoriais podem acelerar a configuração, mas nunca devem ser
apresentados como conformidade garantida. Uma alteração legal ou um requisito
setorial deve originar revisão humana e uma nova versão do modelo ou da regra.

## Papel limitado da inteligência artificial

A inteligência artificial pode extrair, resumir, comparar e sugerir. Não deve
ativar controlos, alterar limites, encerrar alertas ou emitir conclusões sem uma
decisão humana registada. As deteções principais do MVP continuam baseadas em
regras determinísticas, com versão, parâmetros e evidência reproduzível.

## Linguagem do produto

Termos adequados:

- alerta;
- exceção aos critérios configurados;
- resultado de um teste;
- evidência associada;
- prioridade para análise;
- conclusão humana;
- rascunho ou dossier de trabalho.

Termos reservados ou potencialmente enganosos, quando não existe o trabalho
profissional correspondente:

- contas auditadas ou certificadas;
- opinião de auditoria;
- garantia de conformidade;
- controlo eficaz ou ineficaz como decisão automática;
- fraude confirmada;
- relatório certificado.

## Implicação para o negócio

Os fundadores não precisam de ser ROC para desenvolver e comercializar o
software dentro destes limites. Uma parceria com ROC ou SROC é, contudo, muito
valiosa para validar a metodologia, integrar o produto no fluxo profissional e
ganhar confiança comercial.

Essa parceria não transfere para o software a habilitação profissional do ROC.
Quando exista um trabalho reservado, a responsabilidade, a revisão e a emissão
do documento permanecem com o ROC ou SROC contratado para esse trabalho.

## Referências oficiais

- [Estatuto da Ordem dos Revisores Oficiais de Contas](https://diariodarepublica.pt/dr/detalhe/lei/140-2015-70196967), em especial os artigos 41.º, 42.º, 44.º e 45.º;
- [Regime Jurídico da Supervisão de Auditoria](https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2015-74094268-74090727);
- [COSO — Internal Control](https://www.coso.org/internal-control);
- [IIA — Three Lines Model](https://www.theiia.org/globalassets/documents/about-us/about-internal-audit/three-lines-model-updated.pdf).

Este documento define limites de produto e não substitui aconselhamento jurídico
para um lançamento comercial ou para um setor regulado.
