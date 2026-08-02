# Contrato do cenário de controlo v1

## Objetivo e identificação

Este contrato define como uma organização descreve e aprova um cenário de
controlo monitorizado pelo AuditFlow AI. O cenário liga um objetivo da empresa a
um risco, a um controlo, a indicadores e a regras determinísticas.

Identificador do contrato: `auditflow-control-scenario-v1`.

O cenário documenta critérios definidos pela organização. Não constitui uma
opinião de auditoria, uma garantia de conformidade ou uma conclusão automática
sobre a eficácia do controlo.

## Unidade e identidade

Um cenário pertence exatamente a uma organização e possui duas identidades:

- `scenario.id` identifica o cenário ao longo do tempo;
- `scenario.version_id` identifica uma versão imutável desse cenário;
- `scenario.key` é uma chave funcional estável, em maiúsculas e underscores;
- `scenario.version` é um inteiro positivo e crescente dentro do cenário.

A combinação `organization.id + scenario.key` identifica o cenário na empresa.
A combinação `scenario.id + scenario.version` e cada `scenario.version_id` são
únicas.

## Sequência obrigatória

Cada versão segue explicitamente esta sequência:

1. `objective`: resultado que a organização pretende proteger;
2. `risk`: acontecimento que pode impedir esse objetivo;
3. `control`: ação preventiva, detetiva ou corretiva definida pela organização;
4. `monitoring.indicators`: medidas usadas para acompanhar desempenho, risco ou
   execução do controlo;
5. `rules`: testes determinísticos que identificam correspondências aos
   critérios configurados;
6. investigação e conclusão humana dos alertas produzidos.

Um KPI, um KRI e um indicador de controlo não são equivalentes ao controlo. Um
indicador fora do objetivo não prova, por si só, que o controlo falhou ou que é
ineficaz.

## Organização e cenário

`organization` contém apenas o UUID e o nome da organização.

`scenario` contém:

- UUID estável do cenário e UUID da versão;
- chave, número da versão, nome e descrição;
- nenhuma referência a cenários de outra organização.

## Objetivo e risco

`objective.category` usa um destes valores:

- `operations`;
- `reporting`;
- `compliance`.

`objective.statement` e `risk.statement` são declarações aprovadas pela
organização. Não são geradas ou alteradas autonomamente pela inteligência
artificial.

## Controlo

`control` contém:

- nome e descrição do procedimento;
- tipo `preventive`, `detective` ou `corrective`;
- frequência `per_transaction`, `per_import`, `daily`, `weekly`, `monthly`,
  `quarterly`, `annual` ou `ad_hoc`;
- função organizacional responsável em `owner_role`;
- uma ou mais descrições da evidência esperada.

A função responsável é texto organizacional e não concede permissões na
aplicação. A associação futura a utilizadores deve respeitar as permissões da
organização e conservar o histórico quando uma pessoa for removida.

## Indicadores

`monitoring.indicators` contém pelo menos um indicador. Cada indicador possui:

- chave única na versão, nome e descrição;
- tipo `kpi`, `kri` ou `control_indicator`;
- unidade `count`, `percentage`, `currency`, `days` ou `ratio`;
- direção `lower_is_better`, `higher_is_better` ou `informational`;
- medição determinística e versionada;
- objetivo de referência, exceto quando a direção é `informational`.

`measurement.metric_key + measurement.metric_version` identifica uma
implementação de métrica registada pela aplicação. `parameters` é sempre um
objeto JSON e `window` usa `per_import`, `daily`, `weekly`, `monthly`,
`quarterly` ou `annual`.

O objetivo do indicador contém apenas `operator` e `value`. Os operadores v1
são `eq`, `gt`, `gte`, `lt` e `lte`; o valor é uma string decimal na mesma
unidade do indicador.

O objetivo do indicador serve para apresentação e acompanhamento. Não cria um
alerta nem modifica uma regra silenciosamente. Quando um limite tiver de gerar
alertas, esse limite deve constar dos parâmetros de uma regra versionada.

`monitoring.reviewer_role` identifica a função que investiga os alertas e
`review_due_days` é um inteiro positivo definido pela organização. Não representa
um prazo legal universal.

## Regras associadas

`rules` contém pelo menos uma regra ativa na versão. Cada associação inclui:

- chave e versão exatas da regra registada;
- parâmetros efetivos, validados pelo esquema dessa versão;
- prioridade dos alertas `low`, `medium`, `high` ou `critical`;
- finalidade da regra dentro do cenário;
- origem e referências.

Cada chave de regra aparece no máximo uma vez na versão do cenário. Trocar a
versão de uma regra exige uma nova versão do cenário.

`origin.type` usa `internal`, `contractual`, `regulatory` ou
`suggested_template`. As referências não são interpretadas como prova de
conformidade e uma origem regulamentar ou contratual não dispensa revisão
humana. Uma regra sugerida por modelo ou inteligência artificial usa
`suggested_template` até ser revista e aprovada por uma pessoa.

Cada referência contém apenas `title` e `reference`. A referência identifica o
documento ou requisito revisto pela organização; não é executada pela aplicação.

A execução não aceita código, SQL, expressões livres nem chamadas externas nos
parâmetros. Apenas chaves de regras e métricas registadas podem ser executadas.

## Governo, aprovação e ativação

Um analista ou proprietário ativo pode preparar um rascunho. O rascunho é
editável, não é uma versão executável e não usa este payload como prova de
configuração aprovada.

A aprovação cria um snapshot com `governance.state = "approved"` e exige:

- criador e data de criação;
- proprietário ativo que aprovou e data de aprovação;
- nota de aprovação e motivo da alteração;
- data de entrada em vigor;
- versão anterior substituída, quando exista.

`created_by` e `approved_by` conservam UUID, email e papel organizacional no
momento da ação. `approved_by.role` é sempre `owner`; alterações posteriores à
associação do utilizador não reescrevem o snapshot.

O contrato v1 permite que criador e aprovador sejam a mesma pessoa, mas regista
essa situação. Uma política futura de segregação pode proibi-la por organização.

Depois da aprovação, o payload é imutável. Alterar objetivo, risco, controlo,
indicador, limite, regra, parâmetro, prioridade, origem ou governo cria uma nova
versão e exige nova aprovação.

A ativação e desativação são registos operacionais separados e auditados; não
alteram o snapshot aprovado. Apenas uma versão aprovada e ativa pode ser usada
em novas execuções. Uma execução futura deve conservar `version_id` e o hash da
configuração utilizada.

Eventos previstos:

- `control_scenario.approved`;
- `control_scenario.activated`;
- `control_scenario.deactivated`.

## Limitações obrigatórias

O payload e as apresentações futuras incluem exatamente estes códigos:

- `not_a_professional_conclusion`: o cenário não constitui opinião de auditoria,
  certificação ou garantia de conformidade;
- `configured_criteria_only`: os resultados representam apenas correspondências
  aos critérios aprovados pela organização;
- `indicators_are_not_controls`: indicadores não substituem o desenho, execução
  e revisão do controlo;
- `human_review_required`: configuração, alterações e conclusões exigem decisão
  humana registada.

## Formato e integridade

O payload segue
`examples/control_scenarios/cenario-controlo-v1.example.json` e usa:

- JSON em UTF-8;
- UUIDs em minúsculas;
- datas no formato `AAAA-MM-DD`;
- instantes em ISO 8601, UTC e terminados em `Z`;
- chaves funcionais em maiúsculas, números e underscores;
- objetos com chaves ordenadas na serialização canónica;
- sem espaços ou quebras de linha na serialização canónica.

O hash é calculado removendo a propriedade de topo `integrity`, serializando o
restante payload com chaves ordenadas, sem espaços e sem escapar Unicode
desnecessariamente, e aplicando SHA-256 aos bytes UTF-8. O resultado é guardado
em `integrity.payload_hash`.

O hash permite identificar a configuração exata usada numa execução. Não é uma
assinatura digital e não transforma a aprovação interna numa certificação
profissional.

Campos desconhecidos não são acrescentados silenciosamente ao contrato v1. Uma
alteração incompatível exige um novo identificador de contrato.
