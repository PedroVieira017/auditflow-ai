# Regra DUPLICATE_INVOICE_EXACT v1

## Objetivo

Identificar grupos de duas ou mais faturas que podem representar o mesmo
documento registado mais do que uma vez. O resultado é um alerta para revisão
humana, não uma conclusão automática de fraude ou pagamento duplicado.

## Chave de comparação

Uma fatura pertence ao mesmo grupo quando todos estes elementos coincidem:

1. identificador do fornecedor normalizado;
2. número da fatura normalizado;
3. data da fatura;
4. valor total com duas casas decimais;
5. moeda.

A normalização textual usa Unicode NFKC, remove espaços exteriores, reduz
sequências de espaços e converte para maiúsculas. A pontuação é preservada.

## Resultado

Cada grupo com pelo menos duas faturas gera um único alerta com:

- severidade média;
- quantidade de faturas coincidentes;
- ação recomendada para comparar os documentos de origem;
- uma evidência por fatura;
- linha de origem e os cinco campos usados na comparação;
- fingerprint SHA-256 estável para a chave e versão da regra.

O alerta começa no estado `new`. A decisão de confirmar, rejeitar ou resolver
o alerta continua a pertencer ao utilizador.

## Limitações deliberadas

A versão 1 não identifica:

- números de fatura parecidos mas diferentes;
- valores aproximados;
- datas diferentes;
- duplicações entre importações diferentes;
- pagamentos duplicados;
- documentos de fornecedores sem identificador estável.

Estas limitações reduzem falsos positivos. Qualquer alargamento da lógica exige
uma nova versão da regra e validação com dados reais.
