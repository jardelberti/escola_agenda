# 🤖 Guia Mestre de Contexto e Infraestrutura - Agenda Escolar

> **FINALIDADE DO DOCUMENTO:**
> Este documento é o **contexto compartilhado e fonte canônica da verdade** entre os agentes de IA (Antigravity, GPT/Codex, Claude e assistentes futuros) e o mantenedor do projeto **Agenda Escolar** (EEB Ricardo Berti / Jardel Berti).
> Todas as decisões técnicas, regras de negócio, infraestrutura, procedimentos operacionais, formatos de dados e limitações estão consolidados aqui.
> **Atenção:** Nunca inclua credenciais reais (senhas, tokens de API ou o conteúdo de chaves privadas) neste arquivo.

---

### 🏷️ Convenção de Classificação das Informações:
* ✅ **[FATO VERIFICADO]**: Comprovado por leitura direta do código, arquivos de configuração do repositório ou execução de comandos.
* 🎯 **[DECISÃO DE PROJETO]**: Escolha intencional de arquitetura ou modelagem, acompanhada da sua motivação e contexto.
* ⚠️ **[LIMITAÇÃO / PROBLEMA CONHECIDO]**: Comportamento que requer atenção especial, restrição técnica ou débito a ser tratado.
* ❓ **[PENDENTE DE CONFIRMAÇÃO]**: Hipótese ou item que ainda necessita de validação com o mantenedor ou auditoria em produção.

---

## 📌 1. Visão Geral do Sistema e Arquitetura Global

O sistema **Agenda Escolar** é uma plataforma web para gestão e agendamento de recursos compartilhados (Salas de Informática, Salas Multimídia, Projetores Móveis, Caixas de Som, etc.) da EEB Ricardo Berti.

* ✅ **Domínio Oficial de Produção**: [https://agendaricardo.com.br](https://agendaricardo.com.br)
* ✅ **Repositório GitHub**: [https://github.com/jardelberti/escola_agenda](https://github.com/jardelberti/escola_agenda)
* 🎯 **Registro de Containers (Docker Registry)**:
  * **Decisão**: Build 100% local na VPS via `docker compose build`.
  * **Motivo**: O repositório externo no Docker Hub foi intencionalmente descontinuado para manter o GitHub como fonte única da verdade, eliminar etapas intermediárias de push/pull e garantir que o código na VPS corresponda exatamente à branch estável `main`.
* ✅ **Stack Tecnológica Principal**:
  * **Backend**: Python 3.11 / Flask (Modular com Blueprints: `auth`, `agenda`, `admin`, `integrations`).
  * **Servidor WSGI**: Gunicorn (2 workers) na porta 5000.
  * **Fila de Tarefas Assíncronas**: Celery integrado com Redis.
  * **Banco de Dados Principal**: PostgreSQL 17 Alpine com SQLAlchemy e Flask-Migrate (Alembic).
  * **Broker / Cache**: Redis Alpine.
  * **Proxy Reverso & SSL**: Nginx no Host da VPS + Certbot (Let's Encrypt) + Cloudflare Proxy (DNS, CDN, terminação SSL externa).

---

## 🌿 2. Estrutura de Branches no Repositório

* ✅ **`main` (Ativa / Produção)**:
  * Sistema estável mono-tenant em produção no `agendaricardo.com.br`.
  * Recursos: autenticação somente por matrícula de professores/administradores (sem senha na implementação atual de `routes/auth.py`), reservas por turnos (matutino e vespertino), limites de cota semanal por professor, bloqueio administrativo de horários, auditoria de cancelamentos, gráficos analíticos com Chart.js, soft-delete (pausa/reativação) de recursos e professores, integração matinal com WhatsApp e rotinas de backup duplo (local + R2).
* 🎯 **`v2-comercial` (Standby / Preservada)**:
  * **Decisão**: Branch preservada para futuro SaaS multi-tenant (`Escola`, `Plano`, Stripe, Google OAuth). Não está em produção e não deve receber merges acidentais da `main`.

---

## 🏛️ 3. Decisões de Arquitetura e Motivações Técnicas

1. 🎯 **Nginx e Certbot no Host da VPS (em vez de Container)**:
   * **Motivo**: Facilidade de renovação automática de certificados Let's Encrypt pelo Certbot nativo do Ubuntu e isolamento da camada de rede externa. O Nginx no host escuta 80/443 e faz `proxy_pass http://localhost:5000`.
2. 🎯 **Cloudflare Proxy na Borda**:
   * **Motivo**: Proteção contra ataques DDoS, mitigação de tráfego malicioso, cache estático e DNS. O modo SSL Full/Strict precisa ser confirmado no painel Cloudflare.
3. 🎯 **Celery + Redis para Operações de Fundo**:
   * **Motivo**: Ações pesadas como restauração de banco de dados (`pg_restore`) não podem bloquear os workers WSGI do Gunicorn (que possuem timeout de 60s). O Celery processa o dump de forma assíncrona, desvinculado do ciclo de requisição HTTP.
4. 🎯 **Desativação Suave (Soft-Toggle `is_active`)**:
   * **Motivo**: Excluir fisicamente um professor ou recurso quebraria a integridade referencial de agendamentos passados e distorceria relatórios históricos. Por isso, recursos e professores inativos permanecem no banco mas são ocultados para novos agendamentos.
5. 🎯 **Modularização por Blueprints Flask**:
   * **Motivo**: Separação clara de responsabilidades:
     * `auth`: Login por matrícula e logout.
     * `agenda`: Calendário, agendamento de slots, cancelamento pelo professor e atualização de WhatsApp pessoal.
     * `admin`: Gestão de professores, recursos, grades de turno, relatórios, auditoria e backups.
     * `integrations`: Endpoints JSON protegidos por token para automações externas (n8n/Evolution API).
6. 🎯 **Compatibilidade com Nomes de Endpoints Legados (`_endpoint_aliases`)**:
   * **Motivo**: Como o sistema foi refatorado de um monólito `app.py` para Blueprints, o handler `handle_build_error` mapeia endpoints legados (ex: `'home'` -> `'agenda.home'`) resolvendo nomes antigos usados em `url_for` nos templates e redirects. Isso não cria redirecionamentos HTTP nem garante compatibilidade de todas as URLs antigas.

---

## 📋 4. Regras de Negócio Críticas

1. ✅ **Turnos e Grades de Horários**:
   * O sistema trabalha com turnos independentes (`matutino` e `vespertino`).
   * Cada recurso pode ter sua própria grade de horários (`schedule_template`), definida em JSON na coluna `slots` (ex: 1º Horário, Recreio, 2º Horário, etc.).
   * Restrição única de banco: `(resource_id, shift)` impede templates duplicados por turno.
2. ✅ **Cota Semanal de Agendamentos (`max_weekly_bookings`)**:
   * Cada recurso pode definir um limite máximo de horários que um professor pode agendar por semana (segunda a domingo).
   * O cálculo é feito pela função `get_teacher_weekly_bookings_count(resource_id, teacher_id, target_date)`. Se o professor atingir o teto, novos agendamentos naquele recurso são bloqueados na mesma semana.
3. ✅ **Prevenção de Duplo Agendamento (Double-Booking)**:
   * Garantida tanto na camada de aplicação quanto no PostgreSQL através do índice único parcial `uq_booking_teacher_active` em `(resource_id, teacher_id, date, shift, slot_name)` onde `status = 'booked'`.
4. ✅ **Bloqueio Administrativo (`status = 'closed'`)**:
   * O administrador pode fechar um horário para manutenção, feriado ou reuniões pedagógicas.
   * Horários com `status = 'closed'` impedem reservas de professores, mas não entram na contagem de cota semanal de nenhum professor.
5. ✅ **Auditoria de Cancelamentos (`booking_audit_log`)**:
   * Toda exclusão/cancelamento de reserva registra na tabela `booking_audit_log`: nome de quem cancelou, se era administrador ou o próprio professor, horário da ação, recurso, data e turno afetados.
6. ✅ **Sanitização de WhatsApp**:
   * Os números de WhatsApp de professores são limpos por `sanitize_phone()` e normalizados removendo caracteres não numéricos e prefixando `55` quando recebem 10 ou 11 dígitos. A função não garante validade do número nem insere obrigatoriamente o nono dígito; `format_phone()` serve para exibição na interface.

---

## 🖥️ 5. Infraestrutura, Servidores e Acessos SSH

```
                       ┌──────────────────────────────────────────────┐
                       │          CLOUDFLARE PROXY & DNS              │
                       │           agendaricardo.com.br               │
                       └──────────────────────┬───────────────────────┘
                                              │ HTTPS (443)
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ VPS PRODUÇÃO - ORACLE CLOUD INFRASTRUCTURE (Ubuntu 24.04 LTS)                          │
│ IP Público: 163.176.251.63                                                             │
│                                                                                        │
│   Nginx (Host: 80 -> 443 SSL Certbot)                                                  │
│     │ proxy_pass http://localhost:5000                                                 │
│     ▼                                                                                  │
│   Docker Stack (docker-compose.yml):                                                   │
│     ├── agenda_app (Flask / Gunicorn :5000) ──────┐                                    │
│     ├── agenda_db (PostgreSQL 17 :5432) ◄─────────┼─── Volume: postgres_data           │
│     ├── agenda_redis (Redis :6379)      ◄─────────┤─── Volume: redis_data              │
│     └── escola_agenda-worker-1 (Celery) ──────────┘                                    │
│                                                                                        │
│   Rotinas Cron Diárias no Host Ubuntu:                                                 │
│     • 00:00 -> /home/ubuntu/escola_agenda/backup_agenda_db.sh (Backup binário local)   │
│     • 03:00 -> /home/ubuntu/escola_agenda/scripts/backup_to_r2.sh (Dump SQL gzip R2)  │
└─────────────────────────────────────▲──────────────────────────────────────────────────┘
                                      │ API Request: GET /api/integrations/daily-summary
                                      │ (07:00 Seg-Sex via Cron n8n)
┌─────────────────────────────────────┴──────────────────────────────────────────────────┐
│ SERVIDOR HOMELAB LOCAL                                                                 │
│ IP Tailscale: 100.81.69.55 | IP LAN: 192.168.0.235 | Usuário: jardel                   │
│                                                                                        │
│   • n8n Container (:5678) ─── Workflow 'agendaEscola0001'                              │
│     Volume: /srv/homelab/private/n8n -> /home/node/.n8n (SQLite: database.sqlite)      │
│   • Evolution API (:8085) ─── Instância 'agenda-escola' ───► Disparo WhatsApp         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.1. VPS Produção (Oracle Cloud Infrastructure)
* 🎯 **Infraestrutura informada pelo mantenedor**: Oracle Cloud Infrastructure. Enquadramento Always Free e versão exata do Ubuntu pendentes de confirmação; não inferir gratuidade pelo acesso SSH.
* ✅ **IP Público**: `163.176.251.63`
* ✅ **Usuário SSH**: `ubuntu`
* ✅ **Caminho da Chave SSH Privada no PC Windows**:
  ```
  C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key
  ```
* ✅ **Comando de Conexão**:
  ```bash
  ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
  ```
* ✅ **Diretório do Projeto na VPS**: `/home/ubuntu/escola_agenda`

### 5.2. Servidor Homelab (Automações n8n & WhatsApp)
* ✅ **IP Tailscale (VPN Segura)**: `100.81.69.55`
* ✅ **IP Rede Local (LAN)**: `192.168.0.235`
* ✅ **Usuário SSH**: `jardel`
* ✅ **Caminho da Chave SSH Privada no PC Windows**:
  ```
  C:\Users\monit\.ssh\id_homelab
  ```
* ✅ **Comandos de Conexão**:
  ```bash
  # Via Tailscale (VPN)
  ssh -i C:\Users\monit\.ssh\id_homelab jardel@100.81.69.55

  # Via LAN
  ssh -i C:\Users\monit\.ssh\id_homelab jardel@192.168.0.235
  ```

---

## 🐳 6. Detalhamento dos Containers Docker

### 6.1. Na VPS de Produção (`docker-compose.yml`)

| Serviço | Nome do Container | Imagem Base | Volumes Mapeados | Healthcheck | Dependências |
|---|---|---|---|---|---|
| **`app`** | `agenda_app` | `jardelberti/agenda.escola:v1.1` *(build local)* | • `.:/app`<br>• `app_data:/app/data` | `curl -f http://localhost:5000/health \|\| exit 1` (30s) | `db: condition: service_healthy` |
| **`worker`** | `escola_agenda-worker-1` | `jardelberti/agenda.escola:v1.1` *(build local)* | • `.:/app`<br>• `app_data:/app/data` | ⚠️ *Nenhum configurado* | `- db`<br>`- redis` *(não exige db healthy)* |
| **`db`** | `agenda_db` | `postgres:17-alpine` | • `postgres_data:/var/lib/postgresql/data` | `pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}` (10s) | *Nenhuma* |
| **`redis`** | `agenda_redis` | `redis:alpine` | • `redis_data:/data` | ⚠️ *Nenhum configurado* | *Nenhuma* |

### 6.2. No Servidor Homelab (`scripts/n8n-compose.yml`)
* ✅ **Serviço**: `n8n`
* ✅ **Imagem Oficial**: `docker.n8n.io/n8nio/n8n:2.32.6`
* ✅ **Volume Real no Host**: `/srv/homelab/private/n8n` montado em `/home/node/.n8n` no container.
* ✅ **Banco Interno**: SQLite em `/home/node/.n8n/database.sqlite` (no host: `/srv/homelab/private/n8n/database.sqlite`).
* ✅ **DNS Configurado**: `1.1.1.1` e `8.8.8.8` (adicionados no compose para prevenir falhas de resolução ao consultar `agendaricardo.com.br`).
* ✅ **Portas**: `192.168.0.235:5678:5678` e `100.81.69.55:5678:5678`.

---

## 🗄️ 7. Banco de Dados, Modelagem e Evolução de Schema

### 7.1. Conexão
* Host interno do container: `db:5432`
* URI SQLAlchemy: `postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}`

### 7.2. Tabelas Principais
1. **`teacher`**: Professores e admins (`id`, `name`, `registration`, `whatsapp`, `is_admin`, `is_active`).
2. **`resource`**: Salas e equipamentos (`id`, `name`, `description`, `icon`, `sort_order`, `is_active`, `quantity`, `max_weekly_bookings`).
3. **`schedule_template`**: Horários dos turnos (`id`, `resource_id`, `shift`, `slots`).
4. **`booking`**: Reservas e bloqueios (`id`, `resource_id`, `teacher_id`, `teacher_name`, `date`, `shift`, `slot_name`, `status`, `classroom_or_notes`, `created_at`).
5. **`booking_audit_log`**: Histórico de exclusões (`id`, `booking_id`, `resource_name`, `teacher_name`, `date`, `shift`, `slot_name`, `performed_by_name`, `performed_by_is_admin`, `classroom_or_notes`, `action`, `created_at`).

### 7.3. Evolução de Schema: `ensure_schema_updates()` vs. Alembic
* ✅ **O que `ensure_schema_updates()` faz**: Na inicialização do Flask, executa `db.create_all()` e roda comandos idempotentes `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` exclusivamente para:
  * `booking.classroom_or_notes` (VARCHAR 150)
  * `booking.created_at` (TIMESTAMP)
  * `resource.max_weekly_bookings` (INTEGER)
* ⚠️ **[LIMITAÇÃO / ATENÇÃO]**: Essa rotina foi criada para adicionar essas três colunas específicas de forma incremental. Não há garantia de ausência de downtime ou bloqueios no banco. Ela **NÃO substitui o Flask-Migrate (Alembic)** para renomear colunas, criar restrições, índices ou novas tabelas relacionais. Para alterações estruturais profundas, devem ser geradas migrações completas (`flask db migrate` / `flask db upgrade`).

---

## 💾 8. Política de Backups, Formatos e Procedimentos de Restauração

> [!CAUTION] **REGRA DE OURO DOS FORMATOS DE BACKUP (BINÁRIO vs. SQL TEXTUAL):**
> * O comando **`pg_restore`** (utilizado pelo Celery no painel web `/admin/restore` e pelo script `./restore_agenda_db.sh`) **restaura arquivos de formato custom ou tar e backups em diretório**. No painel atual, o upload é de arquivo; o backup gerado pela aplicação é custom (`-F c`). SQL textual não é aceito pelo `pg_restore`.
> * Ter a extensão `.sql` no nome do arquivo gerado pelo painel (`backup_postgres_*.sql`) **NÃO** significa que é SQL textual — ele foi gerado com `pg_dump -F c`.
> * Arquivos de SQL textual puro (como os dumps descompactados do Cloudflare R2) **FALHAM no painel web** com o erro `input file appears to be a text format dump`. Eles devem ser restaurados exclusivamente via **`psql`**.

### 8.1. Rotinas Diárias de Produção (Crontab do usuário `ubuntu` na VPS)
```bash
0 0 * * * /home/ubuntu/escola_agenda/backup_agenda_db.sh >> /home/ubuntu/escola_agenda/backup_cron.log 2>&1
0 3 * * * /home/ubuntu/escola_agenda/scripts/backup_to_r2.sh >> /home/ubuntu/backup_r2.log 2>&1
```

| Rotina | Horário | Mecanismo | Formato | Destino | Retenção |
|---|---|---|---|---|---|
| **Local VPS** | 00:00 | `docker exec agenda_db pg_dump -U agenda_user -d agenda_db -F c` | **Binário Custom** (`.dump`) | `/home/ubuntu/escola_agenda/backups/` | **7 dias** |
| **Cloudflare R2** | 03:00 | `docker exec agenda_db pg_dump ... --clean --if-exists \| gzip` | **SQL Textual Gzip** (`.sql.gz`) | Bucket `r2:agenda-escola-backups` | **30 dias** |

### 8.2. Guia de Procedimentos de Restauração

#### Caso A: Restaurar Backup Binário Local ou Gerado pelo Painel Web (`.dump` ou `.sql` binário)
* **Método 1 (Interface Web)**:
  1. Acesse `https://agendaricardo.com.br/admin/backup-restore`.
  2. No formulário de upload, selecione o arquivo binário.
  3. O endpoint `POST /admin/restore` enfileira a tarefa assíncrona no Celery (`restore_task_bg`), que roda o `pg_restore --clean --if-exists`.
* **Método 2 (Script Interativo na VPS)**:
  ```bash
  ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
  cd /home/ubuntu/escola_agenda
  ./restore_agenda_db.sh
  # Digite o número do backup desejado e confirme com 'SIM'
  ```

#### Caso B: Restaurar Backup do Cloudflare R2 (SQL Textual Puro `.sql.gz`)
* **Procedimento Obrigatório (via `psql`)**:
  ```bash
  # Execute em Bash na VPS, somente quando a restauração estiver autorizada.
  set -euo pipefail

  # 1. Na VPS, baixe o arquivo do bucket R2
  rclone copyto r2:agenda-escola-backups/backup_agenda_YYYYMMDD_HHMMSS.sql.gz ./restore_r2.sql.gz

  # 2. Descompacte e injete via pipeline direto no psql do container
  gunzip -c restore_r2.sql.gz | docker exec -i agenda_db psql -v ON_ERROR_STOP=1 -U agenda_user -d agenda_db

  # 3. Após sucesso, valide os dados antes de excluir o dump temporário
  rm ./restore_r2.sql.gz
  ```

---

## 📲 9. Integrações Externas: n8n, WhatsApp e Evolution API

### 9.1. Endpoints de Integração (Blueprint `integrations`)
* **Endpoint Principal**: `GET https://agendaricardo.com.br/api/integrations/daily-summary`
  * **Parâmetro**: `?date=AAAA-MM-DD` (padrão: data de hoje no fuso `America/Sao_Paulo`).
  * **Autenticação**: Suporta `X-API-Key: <TOKEN>`, `Authorization: Bearer <TOKEN>` ou query param `?token=<TOKEN>`.
  * **Retorno**: JSON com `summary_text` (resumo geral formatado com emojis agrupado por turnos), `teachers_summaries` (lista com mensagens individuais de cada professor com reservas no dia) e `admin_whatsapp`.
* **Endpoint de Professores**: `GET https://agendaricardo.com.br/api/integrations/teachers` (lista status de WhatsApp dos professores).

### 9.2. Workflow no n8n (`agendaEscola0001`)
* ✅ **Disparo**: Seg-Sex às 07:00 via `Cron Expression: 0 7 * * 1-5`.
* ✅ **Fluxo**: Consulta o daily-summary -> Envia o resumo geral para o WhatsApp do Admin (Jardel) -> Itera sobre cada professor e envia lembrete privado individual via Evolution API (`/message/sendText/agenda-escola`).

### 9.3. Script de Gestão do n8n: `scripts/manage_n8n.py`
* 🎯 **Por que este script existe?**
  No **n8n v2.x**, triggers agendados com intervalos do tipo `weeks` caíam em um bug interno que descartava a execução silenciosamente. Além disso, a engine do n8n 2.x lê os nós ativos diretamente da tabela **`workflow_history`** associada ao `activeVersionId`, e não apenas da tabela `workflow_entity`.
* ✅ **O que o script faz**:
  1. Conecta-se ao SQLite do n8n (lê `N8N_DB_PATH`, `/home/node/.n8n/database.sqlite` ou `/data/database.sqlite`).
  2. Ajusta o nó `scheduleTrigger` do workflow `agendaEscola0001` para a Cron Expression direta `0 7 * * 1-5`.
  3. Adiciona política de resiliência nos nós `httpRequest` (`retryOnFail: true`, 3 tentativas, espera 2000ms).
  4. Sincroniza atômicamente tanto `workflow_entity` quanto `workflow_history`.
  5. Limpa workflows temporários de teste antigos.
  6. Cria workflow de teste com agendamento diário no horário HH MM (não é disparo imediato): `python manage_n8n.py --test HH MM`.
* ⚠️ **Execução no Homelab — pré-requisitos e caminhos**:
  * O volume de dados foi confirmado por `docker inspect n8n` em 02/10/2026: `/srv/homelab/private/n8n` no host -> `/home/node/.n8n` no container.
  * A localização de uma cópia de `manage_n8n.py` no homelab ainda não foi confirmada. Não assumir `/home/jardel/escola_agenda/scripts`.
  * Exemplo por variável de ambiente, após localizar/copiar o script e garantir permissão de acesso ao banco:
    ```bash
    N8N_DB_PATH="/srv/homelab/private/n8n/database.sqlite" python3 /CAMINHO_CONFIRMADO/manage_n8n.py
    ```
  * Para um container Python temporário, montar o diretório real de dados em `/data` e o diretório confirmado do script em `/scripts`, usando `--mount type=bind`. Não executar com caminhos hipotéticos; `--mount` rejeita uma origem inexistente.
  * O script altera tabelas internas, ativa o workflow e remove `testeJardel001`. A sincronização ocorre em uma transação SQLite, mas não prova recarregamento imediato do agendador em memória. Preservar backup consistente do SQLite e verificar a aplicação da versão antes de considerar o ajuste concluído.

---

## 🔐 10. Variáveis de Ambiente (`.env`)

O arquivo `/home/ubuntu/escola_agenda/.env` na VPS contém as configurações de produção:

| Variável | Descrição | Exemplo / Valor |
|---|---|---|
| `POSTGRES_USER` | Usuário do banco PostgreSQL | `agenda_user` |
| `POSTGRES_PASSWORD` | Senha segura do banco PostgreSQL | *(definida na VPS)* |
| `POSTGRES_DB` | Nome da base de dados relacional | `agenda_db` |
| `HOST_PORT` | Porta mapeada no Host para a aplicação | `5000` |
| `APP_IMAGE` | Tag da imagem local construída pelo Docker | `jardelberti/agenda.escola:v1.1` |
| `SECRET_KEY` | Chave secreta de sessão Flask e CSRF | *(string aleatória de alta entropia)* |
| `INTEGRATION_API_KEY` | Token de autenticação dos endpoints de integração | *(chave de autorização do n8n/API)* |

---

## 🧪 11. Testes Automatizados e Garantia de Qualidade

* ✅ **Framework**: `unittest` padrão do Python.
* ✅ **Localização dos Testes**: Diretório `tests/`:
  * `test_booking_integrity.py` e `test_multi_resource_capacity.py`: Integridade e capacidade de reservas.
  * `test_backup_and_health.py`: Testes de endpoint `/health`, retenção e limpeza de backups antigos.
  * `test_reports_and_booking_rules.py`: Relatórios e regras de agendamento.
  * `test_teacher_active_status.py`: Ativação/desativação de professores.
  * `test_integrations_and_whatsapp.py`: Integrações e WhatsApp.
  * `test_csrf_protection.py`: Proteção CSRF.
* ✅ **Como Executar os Testes no Ambiente Local (Windows)**:
  ```powershell
  # Usando o Python do ambiente virtual local:
  .\.venv\Scripts\python.exe -m unittest discover tests
  ```
  ❓ **Resultado da suíte**: Antigravity informou 28 testes passando; quantidade e sucesso não foram revalidados por GPT/Codex nesta revisão documental de 02/10/2026. Ao executar a suíte, registrar data, commit, comando, quantidade e resultado. Não tratar esse relato como garantia permanente.

---

## 🚀 12. Procedimento Oficial de Deploy e Manutenção

### 12.1. Ciclo de Atualização em Produção
1. **Desenvolvimento Local**: Sempre na branch estável `main`.
2. **Executar Testes**: `.\.venv\Scripts\python.exe -m unittest discover tests`
3. **Commit e Push**:
   ```bash
   git add .
   git commit -m "feat/fix: mensagem explicativa"
   git push origin main
   ```
4. **Deploy na VPS via SSH**:
   ```bash
   ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
   cd ~/escola_agenda
   git pull origin main
   docker compose build
   docker compose up -d
   docker compose ps
   ```

### 12.2. Diagnóstico e Verificações Operacionais Rápidas
* **Logs da Aplicação Flask**: `docker logs agenda_app -f --tail 50`
* **Logs do Worker Celery**: `docker logs escola_agenda-worker-1 -f --tail 50`
* **Healthcheck HTTP**: `curl -I http://localhost:5000/health` ou `curl -I https://agendaricardo.com.br/health`
* **Acessar Banco de Produção**: `docker exec -it agenda_db psql -U agenda_user -d agenda_db`
* **Conferir Backups no R2**: `rclone ls r2:agenda-escola-backups`
* **Logs dos Crons de Backup**: `tail -n 30 /home/ubuntu/backup_r2.log`

---

## ⚠️ 13. Limitações e Problemas Conhecidos

1. ⚠️ **Healthchecks de Celery e Redis**: O `docker-compose.yml` da VPS não possui healthcheck declarado para `redis` e `worker`. O `worker` também não aguarda o `db` atingir o estado `service_healthy` (depende apenas da inicialização bruta do container).
2. ⚠️ **Legado SQLAlchemy 2.0**: O projeto emite avisos de depreciação `LegacyAPIWarning: The Query.get() method is considered legacy` em rotas legadas. Deve ser progressivamente refatorado para `db.session.get(Model, id)`.
3. ⚠️ **Sufixo do Arquivo de Backup (`.sql` vs `.dump`)**: A rota `/admin/backup` gera o arquivo com sufixo `.sql` apesar de ser binário. Isso pode induzir administradores ao erro de tentar restaurá-lo com `psql` direto sem o `pg_restore`.

---

## ❓ 14. Informações Pendentes de Confirmação

1. ❓ **Conteúdo dos scripts do host VPS (`backup_agenda_db.sh` e `restore_agenda_db.sh`)**: Como estão no `.gitignore` da VPS, recomenda-se criar templates versionados (ex: `scripts/backup_agenda_db.sh.example` e `scripts/restore_agenda_db.sh.example`) no repositório para evitar perda ou descompasso acidental.
2. ❓ **Estabilidade pós-ajuste do n8n**: Confirmar se as execuções diárias das 07:00 no Homelab continuam ocorrendo pontualmente após as atualizações de `workflow_history`.
3. ❓ **Sincronismo de Migrações Alembic**: Confirmar se o diretório `migrations/versions/` reflete exatamente o estado atual das tabelas na VPS antes de rodar novos comandos de migração manual.

## 🤝 15. Protocolo de Contexto Compartilhado entre Agentes

* Ler este guia antes de alterar código ou infraestrutura e respeitar o escopo autorizado pelo mantenedor.
* Conferir afirmações no código/configuração ou no serviço correspondente. Em divergências, registrar a evidência e corrigir o guia; a documentação não substitui a verificação.
* **OBRIGATÓRIO PARA QUALQUER AGENTE DE IA:** toda alteração realizada no projeto (código, testes, documentação, configuração, automação ou infraestrutura) deve ser registrada neste `AGENTS.md` antes de encerrar a tarefa. Atualizar também as seções afetadas, para que qualquer outro agente consiga entender o estado do projeto e prosseguir sem depender do histórico do chat.
* Cada registro deve conter data, agente responsável, o que mudou, motivo, arquivos/serviços afetados, validações efetivamente realizadas e pendências ou próximo passo. Distinguir alteração local, publicação no GitHub e deploy em produção; nunca afirmar que um deploy ocorreu apenas porque houve push.
* Acrescentar os registros na seção 16. Manter as instruções atuais coerentes e usar o histórico Git para detalhes extensos. Registrar trabalho incompleto e bloqueios de forma explícita; não apresentar testes não executados como aprovados.
* Informações transitórias (commit em produção, saúde dos serviços, testes e execuções de cron) devem incluir data e evidência; não inferir estado atual de verificações antigas.
* Não executar exemplos destrutivos, restaurações ou mensagens WhatsApp apenas para validar documentação.
* Não publicar segredos nem confundir decisões relatadas pelo mantenedor com fatos observados por um agente.
* Revisão cruzada GPT/Codex em 02/10/2026: comparação com `routes/auth.py`, `routes/admin.py`, `models.py`, `utils.py`, `app.py`, Compose, script n8n e inventário de `tests/`. Infraestrutura: utilizar as verificações SSH registradas nesta sessão; não foi feito deploy nesta revisão.
## 📝 16. Registro de Alterações e Continuidade

### 2026-10-02 — GPT/Codex — Consolidação do contexto compartilhado

* **Alterações e motivo:** revisão cruzada do guia após revisão do Antigravity; corrigidas autenticação por matrícula, campos dos modelos, inventário de testes, alcance dos aliases de endpoints, normalização de WhatsApp, formatos de restauração, caminhos e efeitos do script n8n. Informações sem evidência foram marcadas como pendentes. Tornado obrigatório o registro neste arquivo por qualquer agente de IA.
* **Arquivo afetado:** `AGENTS.md`; nenhuma mudança em código funcional ou infraestrutura nesta tarefa.
* **Validação:** comparação documental com os arquivos reais e verificações SSH de leitura descritas na seção 15; revisão de diferenças e `git diff --check`. A suíte de testes não foi executada nesta tarefa documental.
* **Publicação:** atualização destinada à branch `main` do GitHub, autorizada pelo mantenedor. Confirmar a conclusão do push no resultado da tarefa e no histórico Git.
* **Produção:** nenhum deploy ou reinício realizado nesta tarefa; publicação da documentação não atualiza automaticamente a cópia da VPS.
* **Continuidade:** consultar as pendências da seção 14 antes de operações relacionadas; manter este registro e as seções afetadas atualizados em cada tarefa futura.
