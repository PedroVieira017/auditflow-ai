# AuditFlow AI

Plataforma em desenvolvimento para preparar, executar e documentar testes de
controlo sobre dados financeiros. O primeiro fluxo analisa faturas de
fornecedores através de regras determinísticas e apresenta exceções com a
respetiva evidência.

O AuditFlow AI é uma ferramenta de apoio a equipas financeiras, profissionais
de controlo e profissionais de auditoria. Não emite certificações legais de
contas, relatórios de auditoria ou opiniões profissionais, nem substitui o
julgamento da gestão, do auditor ou do ROC. Os limites profissionais e o modelo
de responsabilidade estão definidos em
[`docs/product/limites-profissionais.md`](docs/product/limites-profissionais.md).

## Requisitos

- Python 3.13

## Arranque local no Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

A aplicação fica disponível em `http://127.0.0.1:8000/` e o health check em
`http://127.0.0.1:8000/health/`.

## Verificacao

```powershell
python manage.py check
python manage.py test
```

## Configuração

A aplicação lê configuração a partir de variáveis de ambiente. Consulta
`.env.example` para a lista inicial. O ficheiro `.env` não é carregado
automaticamente nem deve ser versionado.

O valor de desenvolvimento da chave secreta só é aceite quando
`AUDITFLOW_ENV=development`. Fora desse ambiente, `DJANGO_SECRET_KEY` é
obrigatória.

SQLite é usado por omissão apenas em desenvolvimento. Os ambientes `staging`
e `production` exigem `DB_ENGINE=postgresql` e as restantes variáveis `DB_*`.

## Modulos

- `accounts`: identidade e acesso;
- `organizations`: isolamento entre empresas;
- `imports`: receção e validação de ficheiros;
- `invoices`: registos normalizados;
- `rules`: testes de controlo e regras de análise versionados;
- `alerts`: alertas e respetiva triagem;
- `audit_log`: registo de ações;
- `core`: funcionalidades transversais, incluindo o health check.

## Modelo inicial

As entidades de cliente usam UUIDs e incluem uma referência obrigatória à
organização. As relações entre entidades de organizações diferentes são
rejeitadas durante a gravação. As restrições de unicidade continuam também
presentes na base de dados.

O modelo inclui organizações, membros, importações, faturas normalizadas,
definições e execuções de regras, alertas, evidências, alterações de estado e
eventos de auditoria.

## Primeiro contrato de dados

O formato controlado para faturas de fornecedores está documentado em
[`docs/contracts/faturas-fornecedores-v1.md`](docs/contracts/faturas-fornecedores-v1.md).
Os exemplos verificáveis encontram-se em `examples/csv/`.

## Testar o upload localmente

Cria um utilizador administrativo e inicia a aplicação:

```powershell
python manage.py createsuperuser
python manage.py runserver
```

Em `http://127.0.0.1:8000/admin/`, cria uma organização e associa o utilizador
através de um `Membership` com papel `owner` ou `analyst`. O formulário fica em:

```text
/organizations/<organization-id>/imports/new/
```

Os ficheiros são guardados com nomes aleatórios fora das rotas públicas. O
nome original é apenas metadado e nunca determina o caminho de armazenamento.

Após o upload, o CSV é validado de forma síncrona. As faturas só são criadas se
todas as linhas forem válidas; qualquer erro faz falhar a importação completa e
fica disponível na página de detalhe. Numa importação válida, o sistema executa
a regra determinística de potenciais faturas duplicadas e guarda cada alerta com
as evidências que o originaram.

O contrato puro e versionado do motor de regras está descrito em
[`docs/architecture/motor-de-regras.md`](docs/architecture/motor-de-regras.md).
A primeira regra de auditoria está documentada em
[`docs/rules/faturas-duplicadas-v1.md`](docs/rules/faturas-duplicadas-v1.md).
