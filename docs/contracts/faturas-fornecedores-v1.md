# Contrato CSV — faturas de fornecedores v1

## Objetivo

Este contrato define a única entrada aceite pelo primeiro fluxo vertical do
AuditFlow AI. O ficheiro representa faturas de fornecedores e será usado pela
regra determinística de potenciais duplicados.

Identificador do contrato: `supplier-invoices-v1`.

## Formato do ficheiro

- extensão: `.csv`;
- codificação: UTF-8, com ou sem BOM;
- separador: ponto e vírgula (`;`);
- primeira linha: cabeçalho obrigatório;
- máximo: 10 MiB e 50 000 linhas de dados;
- finais de linha: LF ou CRLF;
- linhas vazias no meio dos dados não são aceites;
- colunas adicionais, em falta ou repetidas não são aceites.

O cabeçalho e a sua ordem são fixos:

```text
fornecedor_id;numero_fatura;data_fatura;valor_total;moeda
```

## Campos

| Campo | Obrigatório | Regra |
|---|---:|---|
| `fornecedor_id` | Sim | Identificador estável do fornecedor no sistema de origem, máximo 120 caracteres. |
| `numero_fatura` | Sim | Referência original da fatura, máximo 120 caracteres. |
| `data_fatura` | Sim | Data válida no formato `AAAA-MM-DD`. |
| `valor_total` | Sim | Valor positivo, sem separador de milhares, com vírgula e exatamente duas casas decimais. |
| `moeda` | Sim | Código ISO 4217 com três letras maiúsculas, inicialmente `EUR`. |

O maior valor representável no modelo atual é
`9999999999999999,99`. Zeros, valores negativos, notas de crédito e outras
moedas serão tratados numa versão posterior do contrato.

Os campos de texto não podem começar por `=`, `+`, `@`, tabulação ou carriage
return. Esta regra reduz o risco de execução de fórmulas quando os dados forem
posteriormente abertos numa folha de cálculo.

## Comportamento perante erros

A importação é atómica: se uma linha for inválida, nenhuma fatura desse
ficheiro é persistida. O resultado deve indicar a linha, o campo e um código de
erro estável. A primeira linha de dados é a linha 2, porque a linha 1 contém o
cabeçalho.

O nome original do ficheiro é apenas informativo. O sistema calculará um hash
SHA-256 e não aceitará duas importações idênticas na mesma organização.

## Regra de duplicados v1

Para fins de comparação, `fornecedor_id` e `numero_fatura` são normalizados da
seguinte forma:

1. normalização Unicode NFKC;
2. remoção de espaços no início e no fim;
3. substituição de sequências de espaços por um único espaço;
4. conversão para maiúsculas;
5. preservação de pontuação, barras e hífenes.

Uma potencial duplicação existe quando duas ou mais linhas do mesmo ficheiro
possuem a mesma chave:

```text
fornecedor normalizado
+ número da fatura normalizado
+ data da fatura
+ valor decimal
+ moeda
```

A regra não procura ainda duplicados entre importações, números de fatura
parecidos, datas diferentes ou valores aproximados. Estes casos aumentariam o
número de falsos positivos e exigem validação separada.

## Exemplos verificáveis

- `examples/csv/faturas_validas.csv`: seis linhas válidas e um grupo duplicado;
- `examples/csv/faturas_validas.expected.json`: resultado esperado;
- `examples/csv/faturas_invalidas.csv`: uma linha por categoria de erro;
- `examples/csv/cabecalho_invalido.csv`: exemplo com uma coluna não permitida;
- `examples/csv/erros_esperados.json`: erros esperados nos ficheiros inválidos.

Qualquer alteração incompatível ao cabeçalho, formato ou semântica criará um
novo identificador de contrato. O contrato v1 não será alterado silenciosamente.
