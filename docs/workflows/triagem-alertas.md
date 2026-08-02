# Triagem humana de alertas

## Objetivo

A triagem regista a análise feita por uma pessoa sobre uma exceção produzida por
um teste de controlo. Não transforma o alerta numa opinião de auditoria e não
confirma automaticamente fraude, erro material ou deficiência de controlo.

## Permissões

- proprietários e analistas podem registar decisões;
- leitores podem consultar o alerta, as evidências e todo o histórico;
- utilizadores sem associação ativa à organização não podem consultar nem
  alterar o alerta.

## Estados

- `Novo`: ainda não existe uma conclusão humana registada;
- `Válido`: a exceção indicada pelo teste foi confirmada e deve ser acompanhada;
- `Falso positivo`: os dados satisfazem a regra, mas a investigação concluiu que
  não existe uma ocorrência relevante;
- `Resolvido`: a ocorrência foi tratada e a ação necessária foi concluída.

O estado `Válido` confirma apenas a exceção analisada. Não equivale a uma
conclusão sobre as contas, a eficácia global de um controlo ou a existência de
fraude.

## Regras do fluxo

1. Qualquer mudança tem de selecionar um estado diferente do atual.
2. A justificação é obrigatória e tem um máximo de 2 000 caracteres.
3. O estado anterior, o novo estado, a justificação, o autor e a data ficam
   registados num evento histórico que a interface não permite editar ou apagar.
4. A mudança do alerta, o evento de estado e o evento de auditoria são gravados
   na mesma transação.
5. Se outra pessoa alterar o alerta entretanto, um formulário antigo é recusado
   e o utilizador tem de rever o estado atual antes de decidir.
6. Uma decisão pode ser corrigida através de uma nova mudança; o histórico
   anterior não é apagado.
