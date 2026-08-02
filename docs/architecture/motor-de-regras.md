# Contrato do motor de regras

## Objetivo

O motor executa regras determinísticas sobre dados já validados. Não conhece
HTTP, formulários, armazenamento de ficheiros ou o ORM do Django. Esta separação
permite testar a lógica de auditoria apenas em memória e reproduzir qualquer
resultado com os mesmos dados, parâmetros e versão da regra.

## Entrada

Uma regra recebe um `RuleContext` imutável com:

- identificador da organização;
- identificador da importação;
- tuplo de `InvoiceFact`;
- parâmetros explícitos da execução.

Cada `InvoiceFact` contém apenas os campos canónicos necessários às regras. Uma
regra não pode consultar fontes externas nem modificar estes dados.

## Metadados e versionamento

Cada implementação expõe `RuleMetadata` com chave, versão positiva, nome,
descrição, severidade predefinida e esquema informativo de parâmetros.

A combinação `key + version` é imutável. Uma alteração de comportamento cria
uma versão nova; nunca modifica silenciosamente uma versão existente. O
`RuleRegistry` rejeita duas implementações com a mesma combinação.

## Resultado

A regra devolve zero ou mais `RuleFinding`. Cada finding inclui:

- identidade estável e serializável em JSON;
- título;
- explicação;
- severidade;
- ação recomendada;
- uma ou mais evidências.

O motor transforma a identidade, chave e versão da regra num fingerprint
SHA-256. A ordem das chaves da identidade não altera esse fingerprint.

Cada evidência referencia uma fatura que pertence ao contexto e inclui os
factos usados na conclusão. O motor rejeita findings sem evidências, referências
externas ao contexto, identidades repetidas e valores não serializáveis.

## Fronteira desta tarefa

`execute_rule()` apenas valida e devolve `EvaluatedFinding` em memória. A
criação de `RuleRun`, `Alert` e `AlertEvidence` na base de dados será feita pelo
adaptador de persistência da tarefa seguinte, juntamente com a primeira regra
real de faturas duplicadas.
