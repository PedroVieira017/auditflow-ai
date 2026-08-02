# Contrato do dossier de trabalho v1

## Objetivo e identificação

Este contrato define o primeiro documento exportável do AuditFlow AI: um
snapshot factual de uma importação concluída, das regras executadas, dos alertas
produzidos, das evidências associadas e das decisões humanas registadas.

Identificador do contrato: `auditflow-work-dossier-v1`.

O documento deve usar a designação **Dossier de análise de alertas — Não
certificado**. Não é uma certificação legal das contas, um relatório de revisão
voluntária, uma opinião de auditoria ou uma garantia de conformidade.

## Unidade e condições de geração

- um dossier corresponde exatamente a uma organização e uma importação;
- a importação tem de estar no estado `completed`;
- são incluídas todas as execuções de regras associadas à importação;
- execuções falhadas são identificadas pelo estado, sem expor mensagens técnicas
  internas;
- são incluídos todos os alertas dessas execuções, independentemente do estado;
- um dossier sem alertas é válido e apresenta contagens iguais a zero;
- apenas proprietários e analistas ativos podem gerar o ficheiro;
- a geração nunca altera o estado de um alerta ou de uma decisão;
- um utilizador sem associação ativa à organização não pode gerar o dossier.

O dossier é um snapshot no momento da geração. Decisões posteriores não alteram
um ficheiro já descarregado e exigem a geração de um novo dossier.

## Conteúdo obrigatório

### 1. Identificação do documento

- identificador UUID da geração;
- identificador e versão do contrato;
- data e hora de geração;
- identificador e email do utilizador que gerou o dossier;
- classificação `internal_working_document`;
- indicação `not_certified`.

### 2. Organização e âmbito

- identificador e nome da organização;
- identificador da importação;
- nome original do ficheiro, apenas como metadado;
- hash SHA-256 do ficheiro importado;
- estado e data de conclusão da importação;
- utilizador que realizou o carregamento, quando ainda existir;
- número total de linhas, linhas válidas e linhas inválidas.

O ficheiro CSV original, o caminho interno de armazenamento e linhas que não
constituam evidência de um alerta não são incluídos.

### 3. Execuções de regras

Para cada execução:

- identificador da execução;
- chave, versão, nome e descrição da regra;
- parâmetros efetivamente utilizados;
- estado, início, conclusão e número de alertas;
- nenhuma mensagem técnica interna de erro.

### 4. Resumo factual

- número de execuções de regras;
- número total de alertas;
- contagens de alertas por estado;
- contagens de alertas por prioridade.

As contagens representam apenas o âmbito da importação. Não constituem uma
classificação global de risco, uma avaliação da eficácia dos controlos ou uma
conclusão sobre as contas.

### 5. Alertas e evidências

Para cada alerta:

- identificador, fingerprint e identificador da execução da regra;
- título, explicação, prioridade e estado atual no momento da geração;
- ação recomendada, quando exista;
- data de criação;
- evidências que fundamentaram o alerta;
- histórico completo das decisões humanas.

Cada evidência contém apenas:

- identificador da evidência e do registo de fatura;
- número da linha no ficheiro importado;
- snapshot dos factos usados pela regra.

Cada decisão contém:

- identificador do evento;
- estado anterior e novo estado;
- justificação;
- identificador e email do autor, ou indicação de utilizador removido;
- data e hora da decisão.

## Limitações obrigatórias

O payload e a apresentação devem incluir estes códigos e respetivas mensagens:

- `not_an_audit_opinion`: o dossier não constitui opinião ou relatório de
  auditoria nem certificação legal das contas;
- `rule_matches_only`: os alertas indicam apenas correspondências aos critérios
  das regras executadas;
- `human_review_required`: fraude, erro material, incumprimento ou deficiência
  de controlo exigem investigação e conclusão profissional próprias;
- `scope_limited_to_import`: o âmbito está limitado à importação identificada e
  não representa a totalidade das operações da organização.

O dossier v1 não contém texto gerado por inteligência artificial, previsões,
pontuações globais de risco, assinaturas ou blocos de certificação.

## Formato de dados

O payload segue o exemplo em
`examples/dossier/dossier-trabalho-v1.example.json` e usa estas regras:

- JSON em UTF-8;
- UUIDs em minúsculas;
- datas no formato `AAAA-MM-DD`;
- instantes em ISO 8601, normalizados para UTC e terminados em `Z`;
- valores monetários representados como strings com duas casas decimais;
- estados, prioridades e códigos representados pelos valores estáveis do modelo;
- objetos JSON com chaves ordenadas lexicograficamente na serialização canónica;
- sem espaços ou quebras de linha na serialização canónica;
- execuções ordenadas por chave da regra, versão e UUID;
- alertas ordenados por data de criação e UUID;
- evidências ordenadas por número da linha e UUID;
- decisões ordenadas por data e UUID.

Campos desconhecidos não são acrescentados silenciosamente ao contrato v1. Uma
alteração incompatível cria um novo identificador de contrato.

## Integridade

O hash do payload é calculado assim:

1. construir o objeto completo sem a propriedade de topo `integrity`;
2. serializar em UTF-8, com chaves ordenadas, sem espaços adicionais e sem
   escapar caracteres Unicode desnecessariamente;
3. calcular SHA-256 sobre os bytes resultantes;
4. acrescentar `integrity.algorithm = "sha256"` e o hexadecimal em
   `integrity.payload_hash`.

O mesmo hash deve ser apresentado no documento e guardado no evento de auditoria
`dossier.generated`, juntamente com o contrato, o identificador da geração e o
identificador da importação. O hash deteta alterações ao payload; não equivale a
uma assinatura digital nem identifica juridicamente um signatário.

## Apresentação e nome do ficheiro

A primeira apresentação será um único ficheiro HTML:

- media type `text/html; charset=utf-8`;
- conteúdo completo e estilos incorporados;
- sem JavaScript, imagens ou recursos externos;
- legível no ecrã e preparado para impressão;
- todos os valores provenientes de utilizadores ou importações escapados;
- hash do payload e aviso `Não certificado` visíveis em todas as páginas quando
  impresso.

Nome do ficheiro:

```text
auditflow-dossier-<slug-organizacao>-<AAAAMMDD>-<uuid-importacao>.html
```

O PDF poderá ser acrescentado posteriormente como outra apresentação do mesmo
payload, sem mudar o contrato de dados.

## Retenção e proteção de dados

O dossier pode conter dados financeiros e dados pessoais dos utilizadores que
carregaram ficheiros ou registaram decisões. Deve ser tratado como documento
confidencial e sujeito aos controlos de acesso da organização.

O prazo mínimo de cinco anos previsto nos artigos 75.º e 76.º do Estatuto da
OROC aplica-se aos arquivos profissionais aí definidos para ROC e SROC. Não deve
ser apresentado como prazo universal e automático para qualquer cliente do
AuditFlow AI. A política de retenção do produto terá de considerar a finalidade,
a base jurídica, o contrato e as obrigações aplicáveis a cada cliente.

O artigo 5.º do RGPD exige, entre outros princípios, minimização dos dados e
limitação da conservação. Por isso, o dossier não replica o CSV completo e a
retenção não será fixada nesta versão do contrato.

Referências oficiais:

- [Estatuto da OROC — artigos 75.º e 76.º](https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2015-177026851-177076444);
- [RGPD — artigo 5.º](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679).
