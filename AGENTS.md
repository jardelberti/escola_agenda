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
  * Recursos: professores entram por matrícula; administradores exigem matrícula e senha, com opção de lembrar o dispositivo por sete dias (implementação de 02/10/2026; consultar publicação e ativação na seção 16). Reservas por turnos (matutino e vespertino), limites de cota semanal por professor, bloqueio administrativo de horários, auditoria de cancelamentos, gráficos analíticos com Chart.js, soft-delete (pausa/reativação) de recursos e professores, integração matinal com WhatsApp e rotinas de backup duplo (local + R2).
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
     * `auth`: Login por matrícula de professores, senha obrigatória para administradores, recuperação por link privado, segurança da conta e logout.
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
1. **`teacher`**: Professores e admins (`id`, `name`, `registration`, `whatsapp`, `is_admin`, `is_active`, `password_hash`, `auth_version`). Os dois últimos campos são nulos para professores e administradores ainda sem senha; nenhuma senha em texto puro é armazenada.
2. **`resource`**: Salas e equipamentos (`id`, `name`, `description`, `icon`, `sort_order`, `is_active`, `quantity`, `max_weekly_bookings`).
3. **`schedule_template`**: Horários dos turnos (`id`, `resource_id`, `shift`, `slots`).
4. **`booking`**: Reservas e bloqueios (`id`, `resource_id`, `teacher_id`, `teacher_name`, `date`, `shift`, `slot_name`, `status`, `classroom_or_notes`, `created_at`).
5. **`booking_audit_log`**: Histórico de exclusões (`id`, `booking_id`, `resource_name`, `teacher_name`, `date`, `shift`, `slot_name`, `performed_by_name`, `performed_by_is_admin`, `classroom_or_notes`, `action`, `created_at`).
6. **`admin_access_token`**: Hash SHA-256 do link de criação/recuperação (`token_hash`, `teacher_id`, `expires_at` em Unix seconds). Não possui FK para permitir que dumps anteriores recriem `teacher`; o vínculo e o perfil ativo são conferidos ao consumir o link, e a aplicação remove tokens ao excluir ou alterar o perfil.
7. **`auth_attempt`**: Contadores compartilhados entre workers (`key` em SHA-256, `window_start` em Unix seconds, `attempts`). Incremento atômico; janelas antigas são limpas durante novas tentativas.

### 7.3. Evolução de Schema: `ensure_schema_updates()` vs. Alembic
* ✅ **O que `ensure_schema_updates()` faz**: Na inicialização do Flask, executa `db.create_all()` e roda comandos idempotentes `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` exclusivamente para:
  * `booking.classroom_or_notes` (VARCHAR 150)
  * `booking.created_at` (TIMESTAMP)
  * `resource.max_weekly_bookings` (INTEGER)
* ⚠️ **[LIMITAÇÃO / ATENÇÃO]**: Essa rotina foi criada para adicionar essas três colunas específicas de forma incremental. Não há garantia de ausência de downtime ou bloqueios no banco. Ela **NÃO substitui o Flask-Migrate (Alembic)** para renomear colunas, criar restrições, índices ou novas tabelas relacionais. Para alterações estruturais profundas, devem ser geradas migrações completas (`flask db migrate` / `flask db upgrade`).
* ✅ **Proteção administrativa**: revisão Alembic `d4f2a3b5c6d7`, posterior a `c3e1a2b4d5e6`. `auth_schema.py` aplica somente duas colunas e duas tabelas de segurança, de forma aditiva/idempotente. `scripts/migrate_admin_auth.py` não importa a aplicação e pode rodar antes do reinício para evitar consultas a colunas ainda inexistentes. Não executar migrações históricas ou `stamp` sem conferir a revisão real; o bootstrap não altera `alembic_version`.

### 7.4. Acesso Administrativo e Recuperação
* **Login:** professores seguem por matrícula. Administradores passam pela etapa de senha e só recebem uma sessão após validá-la. Hash scrypt do Werkzeug; senha de 15 a 128 caracteres, com rejeição de padrões muito previsíveis.
* **Dispositivo pessoal:** checkbox explícito “Lembrar neste dispositivo por 7 dias”. Cookies Secure/HttpOnly/SameSite=Lax; sete dias verificados também no servidor, sem renovar automaticamente a validade a cada visita. Sem o checkbox, o cookie de sessão não é persistente. O navegador pode restaurar sessões ao reabrir, conforme sua configuração; usar Sair em computadores compartilhados.
* **Revogação:** identificação administrativa contém ID, versão aleatória e vencimento. Sessões antigas por ID numérico são rejeitadas. Alterar/recuperar senha, restaurar banco ou usar “Sair de todos os dispositivos” invalida os acessos anteriores. Contas desativadas são rejeitadas também em sessões existentes.
* **Confirmação recente:** validade de cinco minutos para restaurar banco, conceder/remover permissões administrativas, alterar matrícula/ativação de administrador, excluir administrador ou emitir link privado. Troca de senha e saída de todos os dispositivos sempre conferem a senha atual. Cadastro e gestão cotidiana de professores/recursos não pedem senha novamente.
* **Tentativas:** até cinco verificações por conta em uma janela de 15 minutos, compartilhada pelo PostgreSQL entre os workers. Sucesso zera o contador. Links também têm limite por token e um limite de 30 por origem observada em 15 minutos; atrás do proxy, a origem pode ser compartilhada. Limitação protege tentativas, mas não elimina possibilidade de bloqueio temporário provocado por terceiros.
* **Criação/recuperação:** nunca permitir que apenas a matrícula cadastre a senha. Administrador autenticado pode usar “Preparar acesso” em Professores. Se ninguém conseguir entrar, o responsável autorizado gera o link via SSH:
  ```bash
  cd /home/ubuntu/escola_agenda
  docker compose exec -T app flask auth access-link MATRICULA
  ```
  O link vale 30 minutos, é de uso único e contém um segredo no fragmento `#`, removido da barra pelo JavaScript. Não copiar para Git, logs, AGENTS.md ou capturas. Emitir outro link invalida o anterior. O titular deve definir sua senha diretamente no formulário; nunca pedir a senha pelo chat.
* **Páginas de entrada/definição:** assets locais, CSP sem scripts externos, `Cache-Control: no-store` e `Referrer-Policy: no-referrer`. `/admin/security` oferece mudança de senha e revogação de todos os dispositivos.
* **Desenvolvimento HTTP local:** `COOKIE_SECURE=false` somente em prévia restrita a loopback com banco fictício. Produção usa HTTPS e cookies Secure. `PUBLIC_BASE_URL` define a origem confiável dos links (padrão `https://agendaricardo.com.br`); não derivar links privados de um Host arbitrário.

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
  4. A tarefa prepara os campos de segurança e revoga sessões/links administrativos após a tentativa de restauração, inclusive em falha parcial. Um backup anterior à criação da senha exige novo link privado via SSH. Não testar restauração em produção apenas para validar essa regra.
* **Método 2 (Script Interativo na VPS)**:
  ```bash
  ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
  cd /home/ubuntu/escola_agenda
  ./restore_agenda_db.sh
  # Digite o número do backup desejado e confirme com 'SIM'
  # Após uma restauração manual, preparar segurança e revogar acessos históricos:
  docker compose exec -T app python scripts/migrate_admin_auth.py --after-restore
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

  # Reaplicar campos de segurança e revogar sessões/links históricos
  docker compose exec -T app python scripts/migrate_admin_auth.py --after-restore

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
  3. Adiciona política de resiliência nos nós `httpRequest`: `retryOnFail: true`, `maxTries: 3`, `waitBetweenTries: 2000` **na raiz do objeto do nó**, junto de `name` e `type`. Campos gravados em `parameters.options` não habilitam o retry da engine e devem ser removidos preservando as demais opções HTTP.
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

* `MONITOR_API_KEY`: chave aleatória exclusiva do `POST /api/integrations/monitor/whatsapp` (header `X-Monitor-Key`), sem permissão para consultar professores ou agendamentos. Sem chave configurada, o endpoint recusa publicações. Nunca registrar seu valor neste guia.

### Monitoramento operacional na Visão Geral

* `operations.py` lê snapshots sanitizados em `/app/data/operations/{whatsapp,vps}.json`, armazenados no volume `app_data`; leitura do painel não consulta rede nem dispara fluxos. Ausência de atualização por 15 minutos é exibida como indisponibilidade/desatualização.
* `scripts/collect_n8n_health.js`: executar dentro do container n8n com Node 24/`node:sqlite`, banco em modo somente leitura e decoder `flatted` já instalado no n8n. Lê versão publicada, cron/fuso e metadados das últimas execuções. Publica somente horário/status/modo/contagem agregada. Nunca publica nomes, números, textos de mensagens, credenciais ou erros brutos. `--dry-run` imprime apenas esses metadados sem publicar. Chave lida de `/home/node/.n8n/agenda-monitor-key`, arquivo privado fora do Git.
* A execução das 7h só é confirmada para uma execução `trigger` bem-sucedida na data útil esperada e janela 06h55–07h10 em São Paulo; após 07h10, ausência de execução é alerta. Execuções manuais ou testes fora desse horário não tornam o indicador verde. Sucesso/ID da Evolution confirma aceitação pela API, não entrega ao destinatário; históricos retidos/prunados podem não permitir contagem.
* `scripts/collect_vps_health.py`: no host VPS, verifica `/health`, `pg_isready`, Redis PONG, Celery pong; lê arquivos `.dump` do diretório `backups/` e lista objetos R2 via `rclone lsjson`, sem gerar/restaurar/remover backups. Arquivos com mais de 36 horas geram atenção. Existência de um arquivo não comprova restauração.
* Coletas instaladas a cada 5 minutos por crontab dos usuários dos hosts, com `flock` para impedir sobreposição. `scripts/install_monitor_cron.py vps|homelab` preserva tarefas existentes e backup privado do crontab; só executar para aplicar/reaplicar a configuração autorizada. A instalação efetiva e os caminhos do Homelab são registrados na seção 16. Mudanças nos coletores exigem atualizar também a cópia do Homelab; o deploy da VPS não faz essa cópia automaticamente.

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
| `COOKIE_SECURE` | Cookies somente via HTTPS; `false` exclusivamente em prévia HTTP local isolada | `true` por padrão no código |
| `PUBLIC_BASE_URL` | Origem confiável dos links administrativos | `https://agendaricardo.com.br` por padrão no código |

---

## 🧪 11. Testes Automatizados e Garantia de Qualidade

* `test_operations.py`: snapshots de saúde, atraso de coleta, horários úteis, distinção entre execução manual e automática, sanitização e chave exclusiva do monitoramento.

* ✅ **Framework**: `unittest` padrão do Python.
* ✅ **Localização dos Testes**: Diretório `tests/`:
  * `test_booking_integrity.py` e `test_multi_resource_capacity.py`: Integridade e capacidade de reservas.
  * `test_backup_and_health.py`: Testes de endpoint `/health`, retenção e limpeza de backups antigos.
  * `test_reports_and_booking_rules.py`: Relatórios e regras de agendamento.
  * `test_teacher_active_status.py`: Ativação/desativação de professores.
  * `test_integrations_and_whatsapp.py`: Integrações e WhatsApp.
  * `test_csrf_protection.py`: Proteção CSRF.
  * `test_n8n_retry_configuration.py`: Migração dos campos de retry, preservação de opções HTTP e idempotência (sem envio de mensagens).
  * `test_admin_authentication.py`: Senha administrativa, sessão de sete dias, cookies, revogação, links privados, throttling, CSRF, promoção protegida, restauração protegida e schema idempotente. `auth_helpers.py` fornece credenciais apenas para fixtures; produção nunca o importa.
* ✅ **Como Executar os Testes no Ambiente Local (Windows)**:
  ```powershell
  # Sempre usar banco isolado: a suíte cria e altera dados de teste.
  $env:DATABASE_URL = 'sqlite:///' + ($env:TEMP -replace '\\','/') + '/agenda_tests_' + [guid]::NewGuid().ToString('N') + '.db'
  .\.venv\Scripts\python.exe -m unittest discover tests
  ```
  ✅ **Resultado verificado em 02/10/2026:** 48 testes aprovados em SQLite temporário isolado durante a implementação da proteção administrativa. Essa validação é local; não equivale a um teste destrutivo no PostgreSQL de produção. Ao alterar o código, executar verificações adequadas e registrar o resultado da nova revisão.

---

## 🚀 12. Procedimento Oficial de Deploy e Manutenção

### 12.1. Ciclo de Atualização em Produção

1. Desenvolver localmente na `main`, atualizar este guia e executar verificações adequadas à mudança.
2. Revisar o diff, criar commit apenas dos arquivos pretendidos e publicar no GitHub.
3. Na VPS, executar `bash scripts/deploy.sh` a partir de `/home/ubuntu/escola_agenda`. Na primeira instalação do script, atualizar o checkout com `git pull --ff-only origin main` e aplicar separadamente a configuração já recebida; nas próximas tarefas, o script deve rodar antes do pull para identificar o diff.
4. Conferir revisão local/GitHub/VPS, aplicação, banco e worker. Registrar resultados e pendências neste arquivo; atualizações finais exclusivamente documentais não exigem novo build.

**Comportamento de `scripts/deploy.sh`:**

* Exige checkout limpo na `main`, histórico fast-forward e lock para evitar dois deploys simultâneos.
* Documentação, scripts operacionais e testes: apenas atualiza o checkout. Mudanças em scripts não aplicam automaticamente configurações externas (n8n, cron ou swap); executar somente os procedimentos específicos autorizados.
* Código/templates/assets: atualiza e reinicia app/worker, aproveitando os bind mounts `.:/app`, sem reinstalar dependências.
* Mudanças em `auth_schema.py` ou `scripts/migrate_admin_auth.py`: após o fast-forward, executa o bootstrap aditivo de segurança no container app antes de reiniciar. A primeira instalação desse trecho exige usar a versão nova do script para aplicar a migração antes do restart; não executar a versão antiga e presumir que ela conhece a migração. Conferir backup e estado Alembic; aplicar a revisão específica apenas quando seu predecessor estiver confirmado.
* Compose: aplica `docker compose up -d --no-build`.
* Dockerfile, requisitos/dependências ou `.dockerignore`: verifica tarefas ativas/reservadas/agendadas do Celery, pausa o worker somente se a consulta válida indicar ausência de tarefas e faz parada graciosa sem timeout de encerramento. Se o worker não responder, cancela o deploy para revisão manual.
* Constrói uma única imagem com `docker compose --parallel 1 build app`; o worker reutiliza essa imagem e não possui `build` próprio. Preserva cache; não usar `--no-cache` ou limpar o cache rotineiramente. Após build, aplica os serviços e confirma `/health` e resposta `pong` do Celery.
* Se houver falha após pausar o worker, tenta iniciá-lo novamente via trap. O script não faz rollback automático do checkout nem migrações completas: interromper, registrar e avaliar falhas antes de repetir um deploy.

**Swap na VPS (configurado em 02/10/2026):**

* Arquivo `/swapfile-agenda`: 2 GiB, permissão 600; persistência em `/etc/fstab`.
* `vm.swappiness=10` em `/etc/sysctl.d/99-agenda-swap.conf`; backup prévio do fstab em `/etc/fstab.agenda-before-swap-20261002`.
* Verificar com `swapon --show`, `free -m` e `sysctl vm.swappiness`. Swap é margem para picos, não substitui RAM; uso persistente elevado exige investigar consumo e recursos da VPS.

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
* **Sincronização autorizada pelo mantenedor:** ao concluir alterações neste projeto, manter o checkout local, a branch `main` no GitHub e o checkout da VPS atualizados na mesma revisão, incluindo esta documentação. O mantenedor autorizou commit, push e deploy como parte desse fluxo; uma instrução posterior para apenas revisar ou não publicar prevalece. Antes de atualizar, conferir alterações locais/remotas e não sobrescrever trabalho de terceiros. Usar atualização fast-forward, executar as verificações adequadas à mudança e validar os serviços após deploy. Registrar e informar qualquer bloqueio ou divergência; nunca declarar sincronização sem comparar os commits. Não há monitoramento contínuo implícito fora das tarefas.
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


### 2026-10-02 — GPT/Codex — Política de sincronização e deploy

* **Alteração:** orientação explícita para manter local, GitHub e VPS na mesma revisão ao concluir tarefas, conforme autorização do mantenedor.
* **Escopo:** documentação em AGENTS.md e atualização da VPS pelo fluxo oficial; nenhum ajuste funcional solicitado.
* **Validação planejada:** diff sem erros, revisão publicada, comparação dos commits e estado dos quatro serviços após build/deploy. O resultado efetivo será confirmado ao fim da tarefa; em caso de falha, registrar a pendência aqui.

* **Ocorrência operacional desta tarefa:** o build iniciado após a atualização documental apresentou pressão de memória elevada na VPS (952 MB de RAM, sem swap, verificado em 02/10/2026). A reconstrução foi cancelada; a imagem existente foi preservada. Usar atualização documental sem build nesse caso. Saúde e sincronização finais serão verificadas antes do encerramento.

* **Resultado verificado em 02/10/2026, aproximadamente 09h40 (São Paulo):** checkout local, GitHub e VPS sincronizados na revisão df45f32 antes deste registro final; o commit deste registro também deve ser enviado e recebido pela VPS. Atualização com imagem existente executada por docker compose up -d --no-build; quatro containers em execução, PostgreSQL healthy, Redis respondeu PONG e endpoint público /health retornou HTTP 200 com banco conectado. Celery em execução com unless-stopped.
* **Pendência operacional:** Docker marcou agenda_app como unhealthy por timeouts ao iniciar o healthcheck durante a carga elevada, apesar de /health público saudável. Reconstrução cancelada; não foi alterada a configuração de memória, swap ou healthcheck. Confirmar recuperação da carga e do healthcheck em uma verificação posterior; não considerar toda a infraestrutura validada como saudável somente pela sincronização dos arquivos.

* **Recuperação confirmada na verificação final de 02/10/2026:** após a atualização do registro 38b6d4c na VPS, docker inspect agenda_app confirmou healthy. A pendência de healthcheck descrita acima foi resolvida nessa verificação; manter o histórico da ocorrência para evitar novo build desnecessário em alterações documentais.

### 2026-10-02 — GPT/Codex — Otimização de deploy e margem de memória

* **Alterações:** configurados 2 GiB de swap persistente na VPS com swappiness 10; criado `scripts/deploy.sh` com deploy por tipo de alteração, build único/cache, pausa graciosa do worker ocioso e tentativa de retomada em falhas. Removido build duplicado do worker no Compose, mantendo a imagem compartilhada.
* **Motivo:** evitar reconstruções desnecessárias e pressão de memória observada na VPS de 952 MB de RAM.
* **Escopo:** `scripts/deploy.sh`, `docker-compose.yml`, `AGENTS.md` e configuração de swap no host. Nenhuma alteração nas regras de negócio, banco ou integração WhatsApp.
* **Validações:** swap ativo confirmado pelo host; verificar sintaxe Bash, Compose, deploy documental e resposta dos serviços antes de encerrar. Não executar build completo ou restauração apenas como teste; o ramo de build será validado operacionalmente no próximo deploy que realmente altere dependências/imagem.

* **Testes realizados:** bash -n aprovado; cinco cenários com comandos simulados em diretório temporário passaram (documentação sem reinício/build, código com restart, build único, worker ocupado impedindo atualização e falha de build retomando worker). Swap confirmado com 2047 MiB, persistência no fstab e swappiness 10. A suíte funcional da aplicação não foi executada, pois não houve mudança funcional.

* **Aplicação e verificação final em 02/10/2026:** revisão c6833d5 recebida pela VPS, Compose validado e aplicado com --no-build; deploy.sh executado no cenário real sem mudanças pendentes, sem rebuild/restart. Quatro containers em execução, app/db healthy, /health público saudável e Celery respondeu pong. Swap ativo (2 GiB; aproximadamente 193 MiB usados nessa leitura). Registro final publicado e sincronizado pelo fluxo documental; nenhuma restauração ou mensagem WhatsApp executada.

### 2026-10-02 — GPT/Codex — Retry n8n e teste oficial restrito ao administrador

* **Correção:** campos retry estavam em `parameters.options` e eram ignorados pela engine n8n 2.32.6. Corrigidos na raiz dos nós, no utilitário de manutenção e no teste legado; restaurado suporte a `N8N_DB_PATH`/autodetecção. Adicionados dois testes isolados, ambos aprovados.
* **Autorização e isolamento:** mantenedor autorizou mensagem somente para Jardel. Criado backup privado consistente do SQLite com n8n parado; versão temporária do workflow oficial contém somente trigger, consulta e envio ao número do teste anterior de Jardel. Nós de professores removidos dessa versão e cron temporário agendado às 10h22 (São Paulo). Versão principal e histórico sincronizados, com reinício do n8n para recarregar o agendador.
* **Teste antigo:** apenas `active=0` não impediu seu carregamento observado. Após limpar também `activeVersionId` e reiniciar, os logs confirmaram ativação apenas do workflow oficial. Não considerar teste desativado sem verificar a versão publicada e o carregamento efetivo.
* **Backup e reversão:** backup/estado privados armazenados no volume real do n8n; não copiar para o GitHub, pois contêm a configuração completa do workflow. Restaurar conexões dos professores e cron `0 7 * * 1-5` mantendo retries corrigidos após conferir o teste. Não executar o utilitário legado apenas para validar documentação.

* **Resultado real e restauração:** execução 11 do workflow oficial disparou automaticamente em 02/10/2026 às 10h22 (São Paulo), modo trigger, concluída com sucesso em aproximadamente 1,6 segundo. Executados somente agendador, consulta e envio ao administrador; nenhuma execução de nós dos professores. Evolution aceitou uma mensagem, e Jardel confirmou recebimento nesta sessão. Após o teste, restaurados cron 0 7 * * 1-5 e todas as conexões dos professores, com três tentativas/2000 ms nos três nós HTTP. N8n reiniciado para carregar configuração final; teste antigo despublicado. Nenhum disparo manual do workflow completo foi realizado.


### 2026-10-02 — GPT/Codex — Padronização do painel administrativo

* **Alteração e motivo:** unificadas as oito páginas do menu administrativo e a edição de horários em `templates/admin_base.html`, com navegação superior única, largura máxima de 1280 px, margens responsivas, cabeçalho alinhado e tipografia compartilhada em `static/admin.css`. O cadastro de professores passou da coluna lateral para uma seção acima da lista; ações e formulários permanecem disponíveis. A aba selecionada usa `aria-current` e fica visível na rolagem do menu no celular.
* **Arquivos:** `templates/base.html`, `templates/admin_base.html`, `templates/admin_nav.html`, nove páginas administrativas e `static/admin.css`. Nenhuma alteração de banco, regras de agendamento ou automações WhatsApp.
* **Regra para próximas alterações:** páginas administrativas devem estender `admin_base.html`, definir `active_tab` e preencher `admin_content`; não duplicar o menu nem criar wrappers com larguras diferentes. Novas regras visuais compartilhadas devem ficar no CSS administrativo, sem afetar as páginas dos professores.
* **Validação local:** 30 testes aprovados com `.venv/Scripts/python.exe -m unittest discover tests`, usando `DATABASE_URL` em SQLite temporário isolado. Nove páginas conferidas no navegador com dados fictícios em 1440×1000 e 390×844: menu único, aba correta e nenhuma rolagem horizontal da página; o menu possui sua própria rolagem. Avisos legados de SQLAlchemy já documentados continuam presentes.
* **Publicação e produção:** publicação e deploy pelo procedimento da seção 12 fazem parte desta tarefa; o resultado efetivo e a comparação das revisões serão registrados após a verificação dos serviços.

* **Resultado efetivo:** mudança publicada e aplicada na VPS na revisão `d97bf7f` em 02/10/2026. As oito páginas foram abertas em produção com sessão administrativa: largura de 1280 px em tela grande, um menu e uma aba ativa por página, sem transbordamento horizontal. Professores também verificado em 390×844, sem coluna fixa lateral. App e PostgreSQL healthy, `/health` público retornou banco conectado, CSS novo servido pelo domínio. O script confirmou resposta do Celery. Este registro final é exclusivamente documental e deve ser sincronizado sem reinício; comparar a revisão final nas três cópias antes de encerrar.


### 2026-10-02 — GPT/Codex — Proteção administrativa com acesso persistente

* **Escopo autorizado:** senha obrigatória para administradores, lembrança do dispositivo por sete dias e confirmação nas operações críticas, preservando a entrada dos professores por matrícula. Mantenedor autorizou publicação e deploy pela seção 15; definição da senha final cabe ao titular no formulário.
* **Implementação local:** `models.py`, `extensions.py`, `routes/auth.py`, `security.py`, `app.py`, telas/assets locais de autenticação, `/admin/security`, navegação e formulários administrativos. Links de criação/recuperação são privados, de uso único e duração de 30 minutos; não existe ativação pública baseada somente em matrícula. Sessões numéricas antigas, expiradas ou revogadas não dão acesso administrativo. Nenhuma senha real foi definida pelo agente.
* **Schema/restore:** migração aditiva `d4f2a3b5c6d7`, helper `auth_schema.py`, bootstrap `scripts/migrate_admin_auth.py` e execução pré-restart em `scripts/deploy.sh`. Após restore, reaplica campos de segurança e revoga sessões/links; dumps antigos podem exigir recuperação via SSH. Nada foi restaurado em produção como teste.
* **Validação já realizada:** 48 testes aprovados em SQLite temporário isolado, incluindo 18 casos novos de segurança/schema; testes anteriores adaptados para fixtures com senha e IDs autenticados. Prévia local com dados fictícios: login em duas etapas, opção de sete dias, segurança da conta e definição de senha conferidos no navegador; tela de 390×844 sem transbordamento. Scripts externos não são carregados nas páginas de entrada/definição. Avisos legados das bibliotecas permanecem.
* **Pré-verificação de produção (02/10/2026):** somente Jardel é administrador ativo; chave de sessão configurada sem revelar seu conteúdo; Alembic em `c3e1a2b4d5e6`. Contagem naquele momento: 26 professores/usuários, 4 recursos e 1894 reservas. Essas contagens são transitórias e podem mudar com o uso normal.
* **Estado e próximos passos:** implementação local ainda não publicada neste registro. Concluir revisão e sintaxe, proteger backup pré-migração, publicar no GitHub, migrar antes do restart, confirmar serviços/revisões e gerar link de ativação para o titular. Registrar o resultado efetivo após deploy; nunca incluir o segredo do link neste guia.

* **Conclusão efetiva em 02/10/2026 — GPT/Codex:** implementação publicada e aplicada na VPS na revisão `13e62c0`. Reexecutados 48 testes, todos aprovados, com `DATABASE_URL` apontando para SQLite temporário `agenda_auth_resume_20261002.db`; `git diff --check`, sintaxe Bash e Compose aprovados. Backup custom prévio validado por `pg_restore -l`, sem restauração, em `/home/ubuntu/agenda-private-backups/before-admin-auth-20261002.dump` (diretório privado). Migração aditiva executada antes dos reinícios; Alembic atualizado de `c3e1a2b4d5e6` para `d4f2a3b5c6d7`. Nenhum build necessário. App/db healthy, Celery respondeu pong e `/health` público confirmou banco conectado; contagens preservadas: 26 usuários, 4 recursos, 1894 reservas. Tela publicada confirmou etapa de senha e opção de sete dias, sem autenticar nem alterar senha real. Nenhuma mensagem WhatsApp enviada.
* **Continuidade:** criar a senha inicial pelo link privado de uso único entregue ao titular, válido por 30 minutos; senha real permanece sob controle do mantenedor. Até essa definição, o administrador não pode entrar por matrícula apenas. O SQLite local versionado teve a migração aditiva verificada com backup e depois foi preservado em seu conteúdo original, sem publicar dados binários; para executar diretamente sobre esse banco, rodar `python scripts/migrate_admin_auth.py` antes de iniciar a aplicação. Este registro final deve ser sincronizado nas três cópias sem reinício.

### 2026-10-02 — GPT/Codex — Saúde das automações no painel

* **Alteração/motivo:** quatro cartões na Visão Geral para WhatsApp, backup local, R2 e serviços. Distinção entre execução automática matinal, tentativas manuais, testes fora do horário e coleta atrasada; contagem agregada de mensagens aceitas pela API. Consultas não enviam mensagens nem executam backups/restaurações.
* **Arquivos/serviços:** `operations.py`, rotas admin/integrações, templates do dashboard/cartões, Compose/env de exemplo, dois coletores e `tests/test_operations.py`. Chave dedicada e snapshots privados no volume; nenhuma nova tabela ou dependência de build.
* **Validação local:** 56 testes aprovados em SQLite temporário isolado (`agenda_operations_tests_20261002.db`), incluindo 8 regressões novas; coletor n8n validado em modo leitura com execução real 11 (teste automático 10h22, uma aceitação, somente administrador). Prévia local com dados fictícios renderizou quatro cartões e alertou corretamente para ausência do disparo matinal. `git diff --check` aprovado. Publicação/deploy/instalação das coletas ainda pendentes neste registro; registrar o resultado efetivo antes de encerrar.

* **Resultado efetivo em 02/10/2026:** código publicado e implantado na VPS na revisão `df9ba41`, sem build, com app/db healthy, `/health` conectado e Celery pong. Coletor VPS executado: backups encontrados às 00h (local) e 03h (R2); quatro serviços responderam. Coletor Homelab instalado em `/home/jardel/agenda-monitor/collect_n8n_health.js`, SHA-256 conferido com a cópia local; chave dedicada privada (`600`) no volume n8n, autorizada explicitamente pelo mantenedor, sem valor exposto no Git/documentação. Publicação real de metadados aceita pela VPS, sem executar workflow. Cron `*/5` instalado em ambos os usuários, com `flock`; crons de backup preservados. Backups privados anteriores do crontab: `~/.agenda-monitor-cron-before-20261002`. Logs: `/home/ubuntu/agenda-monitor.log` e `/home/jardel/agenda-monitor/monitor.log`. Prévia visual validada em desktop e 390×844, sem transbordamento horizontal. Captura de tela usa dados fictícios e não comprova envio real.
* **Estado esperado:** WhatsApp exibe atenção para o disparo de 02/10 às 07h, pois o registro automático disponível é o teste das 10h22. A próxima execução oficial é 05/10 às 07h; o painel consultará o histórico após essa execução, sem dispará-la. Não declarar entrega garantida nem execução futura como verificada. Este registro e o instalador de cron devem ser publicados/sincronizados sem reinício; instalação das tarefas não prova ainda execução automática do coletor pelo cron.
