# Meu Gestor Financeiro IA

MVP de assistente financeiro pessoal com dashboard web, Flask, SQLite local, PostgreSQL em produção, bot Telegram e integração preparada com Gemini.

## Como rodar no VS Code

```powershell
cd C:\Users\migue\OneDrive\Documentos\gestor_financeiro_ia
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.main
```

Acesse:

```text
http://localhost:5000
```

## Login

Usuario comum demo:

```text
Email: miguel@email.com
Senha: 123456
```

Administrador inicial:

```text
Email: admin@gestor.local
Senha: admin123
```

Voce pode alterar os dados do admin no `.env`:

```env
ADMIN_NAME=Administrador
ADMIN_EMAIL=admin@gestor.local
ADMIN_PASSWORD=admin123
ADMIN_TELEGRAM_ID=
```

Se nao existir admin, ele e criado automaticamente no startup.

## Bot Telegram

1. Crie um bot no BotFather.
2. Coloque o token em `.env` no campo `TELEGRAM_BOT_TOKEN`.
3. Opcionalmente, coloque seu ID em `TELEGRAM_ALLOWED_USER_ID` para restringir o bot.
4. Rode:

```powershell
python -m bot.telegram_bot
```

Sem chave Gemini, o sistema usa interpretação simulada para permitir testes locais.

## Vinculo Telegram x Usuario Web

Cada usuario deve vincular sua conta Telegram pelo sistema web.

Fluxo seguro:

1. Acesse `Configuracoes > Telegram`.
2. Clique em `Gerar codigo de vinculacao`.
3. No bot, envie `/vincular MGF-123456`.
4. O codigo expira em 15 minutos.
5. Depois disso, todas as mensagens usam o `user_id` vinculado ao `telegram_id`.

O bot nao cria usuario automaticamente. Se o Telegram nao estiver vinculado, ele orienta o usuario a gerar um codigo no sistema web.

Para testar:

1. Entre no dashboard com seu usuario.
2. Gere o codigo em `Configuracoes > Telegram`.
3. Envie no Telegram:

```text
/vincular MGF-123456
```

4. Envie no Telegram:

```text
Gastei 50 reais no mercado
```

5. Clique em `Atualizar Dashboard`.
6. Veja o lancamento em `Lancamentos`.
7. Use o filtro de origem `telegram`.

## Administracao

Entre como admin e acesse no menu:

```text
Administracao
```

Telas disponiveis:

- Usuarios
- Detalhes do usuario
- Edicao de dados/status/perfil/senha
- Logs do sistema

Somente usuarios com `role = admin` acessam essas telas.

## Gemini

Para ativar a IA real:

1. Crie uma chave no Google AI Studio.
2. Cole no `.env`:

```env
GEMINI_API_KEY=sua_chave_aqui
GEMINI_MODEL=gemini-1.5-flash
```

Com chave configurada, o Gemini passa a interpretar mensagens do Telegram e analisar fotos de comprovantes.

## Testes rápidos sem Telegram

```powershell
.\.venv\Scripts\python.exe -B -c "from bot.handlers import process_text_message; print(process_text_message('Gastei 50 reais no mercado.'))"
.\.venv\Scripts\python.exe -B -c "from bot.handlers import process_text_message; print(process_text_message('Paguei a internet.'))"
.\.venv\Scripts\python.exe -B -c "from bot.handlers import process_text_message; print(process_text_message('Quais contas vencem essa semana?'))"
```

## Competencia mensal e contas fixas

O sistema separa tres conceitos:

- Conta fixa recorrente: cadastro permanente em `fixed_bills`, como Internet, Energia ou Netflix. Aqui ficam nome, valor previsto, dia de vencimento, categoria e recorrencia.
- Ocorrencia mensal: registro em `fixed_bill_occurrences` para cada mes/ano. Aqui ficam status do mes, vencimento real, valor do mes, pagamento, adiamento e vinculo com lancamento.
- Competencia mensal: mes/ano usado para filtrar Dashboard, Lancamentos, Receitas e Contas Fixas.

Ao criar uma conta fixa, o sistema gera a ocorrencia do mes selecionado. Ao abrir outro mes, a funcao `generate_monthly_fixed_bill_occurrences(user_id, month, year)` cria as ocorrencias faltantes sem duplicar o cadastro principal.

Exemplo:

```text
Cadastro recorrente:
Internet - R$ 99,90 - dia 28 - mensal

Ocorrencias:
06/2026 - Internet - pendente
07/2026 - Internet - pendente
08/2026 - Internet - paga/adiada/cancelada
```

Para testar uma competencia especifica pela API:

```text
/api/dashboard?month=7&year=2026
/api/fixed-bills?month=7&year=2026
/api/transactions?month=7&year=2026
/api/revenues?month=7&year=2026
/api/alerts?month=7&year=2026
```

Quando uma ocorrencia mensal e marcada como paga, o sistema cria ou atualiza um lancamento em `transactions` com origem `conta_fixa` e vincula esse lancamento em `fixed_bill_occurrences.transaction_id`.

## Seletor global de competencia

O header do sistema possui um seletor global com:

- mes anterior;
- mes e ano;
- proximo mes;
- mes atual.

Ao alterar o seletor, o sistema salva `selected_month` e `selected_year` na sessao. As telas principais usam essa competencia automaticamente:

- Dashboard;
- Lancamentos;
- Receitas;
- Contas Fixas;
- Relatorios;
- Assistente IA.

Se a URL receber `month` e `year`, esses valores atualizam a sessao. Se nao receber, o sistema usa a competencia salva. Se nao houver nada salvo, usa o mes atual.

Ao criar lancamento sem data, o sistema usa o primeiro dia da competencia selecionada. Ao criar receita sem data prevista, usa a mesma regra.

## Receitas recorrentes inteligentes

O cadastro de receitas permite configurar recorrencia mensal, quinzenal, semanal ou anual.

Campos principais no banco:

- `is_recurring`
- `recurrence_interval`
- `recurrence_day`
- `recurrence_start_date`
- `ask_value_before_generate`
- `auto_update_default_value`
- `default_amount`
- `next_expected_date`
- `last_generated_date`

A rotina diaria verifica receitas recorrentes, gera a proxima previsao sem duplicar e cria alerta quando `ask_value_before_generate` esta ativo.

## Novo formulario de lancamentos

O formulario de Novo Lancamento usa um painel em duas colunas com:

- tipo visual de despesa/receita;
- resumo em tempo real;
- impacto no saldo da competencia selecionada;
- dicas inteligentes simples;
- centro de custo;
- observacoes;
- recorrencia preparada;
- upload de comprovante em imagem ou PDF;
- lembretes e estrutura futura para divisao.

Campos extras em `transactions`:

- `project_center`
- `notes`
- `is_recurring`
- `recurrence_frequency`
- `recurrence_day`
- `recurrence_end_date`
- `reminder_enabled`
- `split_enabled`
- `receipt_path`

## Anexos financeiros

O sistema nao possui mais uma tela independente de Comprovantes. Arquivos de comprovante agora sao anexos opcionais vinculados a um registro financeiro real:

- `transaction`;
- `revenue`;
- `fixed_bill_occurrence`.

Os arquivos ficam em `app/static/uploads/attachments/`. O banco salva apenas metadados na tabela `financial_attachments`:

- nome original;
- nome armazenado;
- caminho local;
- tipo;
- tamanho;
- origem;
- JSON extraido pelo Gemini, quando existir.

Fotos/documentos enviados pelo Telegram sao baixados em `data/temp/`, analisados pelo Gemini e so sao movidos para `uploads/attachments/` quando o usuario confirma a criacao do lancamento. Se o usuario ignorar, o arquivo temporario e excluido.

## Contas fixas inteligentes

O formulario de Nova Conta Fixa usa um painel em duas colunas com resumo em tempo real, proxima geracao e dicas.

Ele suporta tres cenarios:

- conta fixa comum, como internet;
- conta variavel, como energia, agua ou condominio;
- conta parcelada, como compra em 12 parcelas.

Campos principais em `fixed_bills`:

- `default_amount`
- `payment_method`
- `ask_value_before_generate`
- `auto_update_default_value`
- `recurrence_type`
- `recurrence_interval`
- `start_date`
- `is_installment`
- `total_installments`
- `installment_amount`
- `paid_installments`
- `installment_start_date`
- `installment_total_amount`

Campos principais em `fixed_bill_occurrences`:

- `installment_number`
- `total_installments`
- `is_installment_occurrence`
- `was_value_confirmed`
- `original_default_amount`

A funcao `generate_monthly_fixed_bill_occurrences(user_id, month, year)` gera as ocorrencias do mes selecionado sem duplicar. Para parcelamentos, ela calcula a parcela correta da competencia e para de gerar depois da ultima parcela.

Quando `ask_value_before_generate` esta ativo, o sistema cria um alerta de confirmacao de valor para uso pelo fluxo do Telegram.

## Deploy no Render

### 1. Subir para o GitHub

Antes do deploy, confirme que `.env`, banco local, logs e uploads nao foram versionados. O `.gitignore` ja ignora esses arquivos.

```bash
git add .
git commit -m "Preparar deploy Render"
git push origin main
```

### 2. Criar PostgreSQL no Render

1. No Render, crie um novo PostgreSQL.
2. Copie a `Internal Database URL` para usar no Web Service e no Worker.
3. Configure esse valor na variavel `DATABASE_URL`.

Se `DATABASE_URL` existir, o sistema usa PostgreSQL. Sem `DATABASE_URL`, usa SQLite local em `data/gestor_financeiro.db`.

### 3. Criar Web Service

1. Crie um `Web Service`.
2. Conecte o repositorio GitHub.
3. Configure:

```bash
Build Command: pip install -r requirements.txt
Start Command: gunicorn app.main:app
```

O arquivo `Procfile` declara:

```text
web: gunicorn app.main:app
worker: python -B -m bot.telegram_bot
```

### 4. Variaveis de ambiente

Configure no Render:

```env
APP_ENV=production
SECRET_KEY=gere_uma_chave_forte
DATABASE_URL=postgresql://...
SEED_DEMO_DATA=0
GEMINI_API_KEY=sua_chave
GEMINI_MODEL=gemini-1.5-flash
TELEGRAM_BOT_TOKEN=token_do_bot
TELEGRAM_MODE=polling
ADMIN_NAME=Administrador
ADMIN_EMAIL=seu_email
ADMIN_PASSWORD=senha_forte
ADMIN_TELEGRAM_ID=
```

### 5. Worker do Telegram

Para o bot funcionar no Render com polling, crie tambem um `Background Worker` apontando para o mesmo repositorio.

```bash
Build Command: pip install -r requirements.txt
Start Command: python -B -m bot.telegram_bot
```

No MVP, use `TELEGRAM_MODE=polling`. A variavel `TELEGRAM_MODE` ja existe para preparar webhook futuramente com um endpoint HTTPS dedicado.

### 6. Inicializacao em producao

Ao iniciar, o app:

- conecta no banco configurado;
- cria tabelas se ainda nao existirem;
- cria admin inicial se ainda nao existir;
- nao cria dados demo quando `APP_ENV=production` e `SEED_DEMO_DATA=0`;
- usa `PORT` automaticamente quando executado diretamente.

### 7. Uploads e anexos

O Render pode descartar arquivos locais em reinicializacoes. No MVP, o banco salva metadados dos anexos, mas o arquivo local nao deve ser considerado permanente em producao.

Para producao real, planeje mover anexos para Cloudinary, Supabase Storage ou S3.

### 8. Checklist pos-deploy

1. Acesse a URL do Render.
2. Entre com o admin configurado.
3. Crie ou ajuste usuarios.
4. Gere codigo em `Configuracoes > Telegram`.
5. Envie `/vincular CODIGO` no bot.
6. Teste um lancamento pelo Telegram.
7. Teste Gemini com uma mensagem natural.
8. Teste Dashboard, Receitas, Lancamentos, Contas Fixas, Metas e Relatorios.

## Estrutura

```text
gestor_financeiro_ia/
  app/          Flask, banco, rotas, templates e assets
  ai/           Gemini, leitura de comprovantes e respostas humanizadas
  bot/          Bot Telegram e handlers
  scheduler/    Alertas diarios
  config/       Configuracoes
  data/         Banco SQLite local
```
