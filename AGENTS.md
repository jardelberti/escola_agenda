# 🤖 Guia Mestre de Contexto e Infraestrutura - Agenda Escolar

> **IMPORTANTE PARA AGENTES DE IA (AGENTS / COPILOTS / ASSISTENTES):**  
> Este documento é a **fonte única da verdade** sobre a arquitetura, infraestrutura, credenciais de acesso, bancos de dados, containers, portas, rotinas cron, integrações externas (n8n / WhatsApp / Evolution API) e fluxos de deploy do projeto **Agenda Escolar** (Ricardo Berti).  
> Leia com atenção antes de sugerir ou executar qualquer comando ou alteração.

---

## 📌 1. Visão Geral do Sistema e Arquitetura Global

O sistema **Agenda Escolar** é uma plataforma web para gestão e agendamento de recursos compartilhados (Salas de Informática, Salas Multimídia, Projetores Móveis, Caixas de Som, etc.) utilizada pela equipe escolar da EEB Ricardo Berti.

* **Domínio Oficial de Produção**: [https://agendaricardo.com.br](https://agendaricardo.com.br)
* **Repositório GitHub**: [https://github.com/jardelberti/escola_agenda](https://github.com/jardelberti/escola_agenda)
* **Registro de Containers (Docker Registry)**: **Build 100% local na VPS** via Docker Compose. O repositório externo no Docker Hub foi intencionalmente descontinuado para manter o GitHub como única fonte da verdade e evitar dependências de registries de terceiros.
* **Stack Principal**:
  * **Backend**: Python 3.13 / Flask (Modular com Blueprints: `auth`, `agenda`, `admin`, `integrations`).
  * **Servidor de Aplicação**: Gunicorn com 2 workers WSGI.
  * **Tarefas em Background**: Celery integrado com Redis.
  * **Banco de Dados**: PostgreSQL 17 Alpine com SQLAlchemy e Alembic (Flask-Migrate).
  * **Fila de Mensagens / Cache**: Redis Alpine.
  * **Proxy Reverso & SSL**: Nginx no Host + Certbot (Let's Encrypt) + Cloudflare Proxy (DNS / CDN).

---

## 🌿 2. Estrutura de Branches no Repositório

Existem **apenas duas branches oficiais** no repositório GitHub:

| Branch | Status | Finalidade & Descrição |
|---|---|---|
| **`main`** | **Ativa / Produção** | Versão estável mono-tenant em execução no `agendaricardo.com.br`. Possui gestão de professores, agendamento por turnos (matutino/vespertino), fechamento administrativo de horários, relatórios analíticos com gráficos Chart.js, auditoria de cancelamentos, pausa/reativação de recursos e professores sem exclusão de dados, integração WhatsApp e rotinas de backup. |
| **`v2-comercial`** | **Standby / Preservada** | Versão SaaS multi-tenant em desenvolvimento para comercialização (`Escola`, `Usuario`, `Plano`, `Assinatura`, Stripe, Super Admin, autenticação Google OAuth). **Não está em produção**, mas permanece preservada. |

---

## 🖥️ 3. Infraestrutura, Servidores e Acessos SSH

O ecossistema divide-se entre a **VPS de Produção na Nuvem** e o **Homelab Local**:

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
│   Cron Diário Host:                                                                    │
│     • 00:00 -> backup_agenda_db.sh (Backup local /home/ubuntu/escola_agenda/backups)   │
│     • 03:00 -> backup_to_r2.sh (Upload Cloudflare R2 bucket: agenda-escola-backups)    │
└─────────────────────────────────────▲──────────────────────────────────────────────────┘
                                      │ API Request: GET /api/integrations/daily-summary
                                      │ (07:00 Seg-Sex via Cron n8n)
┌─────────────────────────────────────┴──────────────────────────────────────────────────┐
│ SERVIDOR HOMELAB (Tailscale: 100.81.69.55 / LAN: 192.168.0.235)                        │
│                                                                                        │
│   • n8n Container (:5678) ─── Workflow 'agendaEscola0001'                              │
│   • Evolution API (:8085) ─── Instância 'agenda-escola' ───► Disparo WhatsApp         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.1. Dados da VPS de Produção (Oracle Cloud Infrastructure)
* **Provedor**: Oracle Cloud Infrastructure (OCI) - Always Free Compute.
* **Sistema Operacional**: Ubuntu 24.04.1 LTS (Linux Kernel 7.0.0-1013-oracle x86_64).
* **IP Público**: `163.176.251.63`
* **Usuário SSH**: `ubuntu`
* **Caminho da Chave SSH Privada no PC Windows**:
  ```
  C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key
  ```
* **Comando para Conexão SSH Direta**:
  ```bash
  ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
  ```
* **Diretório Raiz do Projeto na VPS**: `/home/ubuntu/escola_agenda`

### 3.2. Dados do Servidor Homelab (Automação n8n & WhatsApp)
* **IP Tailscale (VPN Segura)**: `100.81.69.55`
* **IP Rede Local (LAN)**: `192.168.0.235`
* **Usuário Homelab**: `jardel`

---

## 🌐 4. Mapeamento de Portas e Serviços de Rede

### 4.1. Na VPS de Produção (IP `163.176.251.63`):

| Porta Host | Protocolo | Serviço | Descrição |
|---|---|---|---|
| **`22`** | TCP | OpenSSH (`sshd`) | Acesso administrativo remoto via chave SSH |
| **`80`** | TCP | Nginx | HTTP -> Redirecionamento 301 automático para HTTPS |
| **`443`** | TCP | Nginx | HTTPS com certificado SSL Let's Encrypt gerenciado pelo Certbot |
| **`5000`** | TCP | Docker (`agenda_app`) | Porta da aplicação Flask exposta em `0.0.0.0:5000` para o proxy Nginx |
| **`5432`** | TCP | Docker (`agenda_db`) | Porta interna PostgreSQL (apenas rede Docker interna, **fechada externamente**) |
| **`6379`** | TCP | Docker (`agenda_redis`) | Porta interna Redis (apenas rede Docker interna, **fechada externamente**) |

### 4.2. No Servidor Homelab (IP Tailscale `100.81.69.55`):

| Porta | Serviço | Descrição |
|---|---|---|
| **`5678`** | n8n | Orquestrador de workflows e automação de disparos matinais |
| **`8085`** | Evolution API | Gateway de WhatsApp (instância ativa `agenda-escola`) |

---

## 🐳 5. Containers Docker em Produção (VPS)

A orquestração na VPS é definida no arquivo `/home/ubuntu/escola_agenda/docker-compose.yml`. Todos os containers usam `restart: unless-stopped` e fuso horário `America/Sao_Paulo`:

| Container | Imagem Base / Imagem Local | Função Técnica | Volumes Mapeados | Healthcheck |
|---|---|---|---|---|
| **`agenda_app`** | `jardelberti/agenda.escola:v1.1` *(build local)* | Aplicação Web Flask com Gunicorn (2 workers) na porta 5000 | • `.:/app`<br>• `app_data:/app/data` | `curl -f http://localhost:5000/health` (intervalo 30s) |
| **`escola_agenda-worker-1`** | `jardelberti/agenda.escola:v1.1` *(build local)* | Worker Celery para tarefas em segundo plano (ex: restauração de banco assíncrona) | • `.:/app`<br>• `app_data:/app/data` | Depende de `db` (healthy) e `redis` |
| **`agenda_db`** | `postgres:17-alpine` | Banco de dados relacional PostgreSQL 17 | • `postgres_data:/var/lib/postgresql/data` | `pg_isready -U agenda_user -d agenda_db` (intervalo 10s) |
| **`agenda_redis`** | `redis:alpine` | Broker e backend de resultados de mensagens do Celery | • `redis_data:/data` | Padrão Docker |

---

## 🗄️ 6. Banco de Dados PostgreSQL & Modelagem

### 6.1. Dados de Conexão Interna
* **Host Interno**: `db` (resolvido automaticamente pelo Docker DNS)
* **Porta**: `5432`
* **Usuário Padrão**: `agenda_user` (definido em `POSTGRES_USER` no `.env`)
* **Banco Padrão**: `agenda_db` (definido em `POSTGRES_DB` no `.env`)
* **String de Conexão SQLAlchemy**:
  ```
  postgresql+psycopg2://agenda_user:SENHA@db:5432/agenda_db
  ```

### 6.2. Tabelas e Regras de Negócio Críticas
1. **`teacher` (Professores e Usuários)**:
   * `id`, `name`, `registration` (matrícula única), `whatsapp` (telefone sanitizado), `is_admin` (booleano), `is_active` (booleano).
   * **Desativação Suave**: Professores inativos (`is_active = FALSE`) não conseguem logar nem receber novas reservas, mas todo o histórico de agendamentos passados permanece intacto.
2. **`resource` (Recursos e Salas)**:
   * `id`, `name`, `description`, `icon`, `sort_order`, `is_active` (booleano), `quantity` (capacidade de agendamentos simultâneos), `max_weekly_bookings` (limite semanal de uso por professor).
   * **Pausa Suave**: Recursos com `is_active = FALSE` não aparecem para novos agendamentos na visão dos professores, preservando dados passados e configurações de horários.
3. **`schedule_template` (Grade de Horários por Turno)**:
   * `id`, `resource_id`, `shift` (`matutino` ou `vespertino`), `slots` (coluna JSON com horários, ex: 1º Horário, Recreio, etc.).
   * Restrição única: `(resource_id, shift)` para evitar grades conflitantes.
4. **`booking` (Agendamentos e Bloqueios)**:
   * `id`, `resource_id`, `teacher_id`, `teacher_name`, `date`, `shift`, `slot_name`, `status` (`booked` ou `closed`), `classroom_or_notes` (turma ou finalidade), `created_at`.
   * **Índice Único Parcial**: `uq_booking_teacher_active` em `(resource_id, teacher_id, date, shift, slot_name)` onde `status = 'booked'` para evitar double-booking do mesmo professor.
5. **`booking_audit_log` (Auditoria de Cancelamentos)**:
   * Registra quem cancelou o agendamento (`performed_by_name`, `performed_by_is_admin`), quando e qual reserva foi cancelada, prevenindo exclusões anônimas.

### 6.3. Atualização Idempotente de Schema (`ensure_schema_updates`)
A aplicação Flask executa automaticamente na inicialização a função `ensure_schema_updates()` localizada em `app.py`. Ela executa `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` para colunas novas, garantindo que deploys atualizem o banco sem dependência obrigatória de migrações manuais por linha de comando.

---

## ⏰ 7. Rotinas de Backup & Cron na VPS

No servidor de produção, existem duas rotinas automáticas de backup configuradas no Crontab do usuário `ubuntu` (`crontab -l`):

```bash
# Crontab de Produção (/var/spool/cron/crontabs/ubuntu):
0 0 * * * /home/ubuntu/escola_agenda/backup_agenda_db.sh >> /home/ubuntu/escola_agenda/backup_cron.log 2>&1
0 3 * * * /home/ubuntu/escola_agenda/scripts/backup_to_r2.sh >> /home/ubuntu/backup_r2.log 2>&1
```

### 7.1. Backup Local Diário (00:00)
* **Script**: `/home/ubuntu/escola_agenda/backup_agenda_db.sh`
* **Mecanismo**: Executa `pg_dump -U agenda_user -d agenda_db -F c` dentro do container `agenda_db`.
* **Destino**: `/home/ubuntu/escola_agenda/backups/agenda_db_YYYY-MM-DD_HH-MM-SS.dump` (formato binário custom do PostgreSQL).
* **Retenção**: Remove backups locais com mais de **7 dias**.
* **Log**: `/home/ubuntu/escola_agenda/backup_cron.log`.

### 7.2. Backup Offsite Diário na Nuvem Cloudflare R2 (03:00)
* **Script**: `/home/ubuntu/escola_agenda/scripts/backup_to_r2.sh`
* **Mecanismo**: Gera dump SQL com `--clean --if-exists`, comprime com `gzip` e faz upload via `rclone`.
* **Destino na Nuvem**: Bucket Cloudflare R2 `r2:agenda-escola-backups`.
* **Configuração Rclone**: `/home/ubuntu/.config/rclone/rclone.conf`.
* **Retenção na Nuvem**: Arquivos com mais de **30 dias** no R2 são eliminados automaticamente pelo script.
* **Log**: `/home/ubuntu/backup_r2.log`.

### 7.3. Restauração do Banco de Dados
Existem dois modos seguros para restaurar um backup:
1. **Via Linha de Comando (Script Interativo)**:
   ```bash
   ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
   cd /home/ubuntu/escola_agenda
   ./restore_agenda_db.sh
   ```
   *O script lista os backups disponíveis numerados e exige a digitação explícita de `SIM` antes de executar o `pg_restore`.*
2. **Via Interface Web**:
   * O administrador acessa `https://agendaricardo.com.br/admin/backup` e faz upload de um arquivo `.dump` ou `.sql`. A tarefa é enfileirada no Celery (`restore_task_bg`) de forma não bloqueante.

---

## 📲 8. Integração WhatsApp & Automação n8n

O sistema possui uma API dedicada para integração com ferramentas de automação (n8n, Evolution API, bots de WhatsApp).

### 8.1. Endpoints de Integração (Blueprint `integrations`)

* **Endpoint Principal**: `GET https://agendaricardo.com.br/api/integrations/daily-summary`
  * **Parâmetros Opcionais**: `?date=AAAA-MM-DD` (padrão: data atual de São Paulo).
  * **Autenticação**:
    * Query param: `?token=<INTEGRATION_API_KEY>`
    * Header: `X-API-Key: <INTEGRATION_API_KEY>`
    * Header: `Authorization: Bearer <INTEGRATION_API_KEY>`
  * **Retorno**: JSON contendo:
    * `summary_text`: Texto formatado com emojis e agrupado por recurso/turno para envio no grupo geral da escola.
    * `teachers_summaries`: Lista com telefones dos professores que têm reserva no dia e mensagem personalizada individual para cada um.
    * `admin_whatsapp`: Telefone do administrador cadastrado para receber o resumo geral.
* **Endpoint de Professores**: `GET https://agendaricardo.com.br/api/integrations/teachers`
  * Retorna a lista de professores com informações sobre presença de WhatsApp cadastrado.

### 8.2. Homelab, n8n e Evolution API
* **Workflow n8n**: `Agenda Escolar - Notificações WhatsApp` (ID: `agendaEscola0001`).
* **Trigger do n8n**: Agendado via Cron Expression `0 7 * * 1-5` (Segunda a Sexta às 07:00 da manhã).
* **Fluxo de Disparo**:
  1. Às 07:00, o n8n consulta o endpoint `/api/integrations/daily-summary`.
  2. Envia a mensagem geral consolidada (`summary_text`) para o WhatsApp do Administrador (Jardel).
  3. Itera sobre cada professor em `teachers_summaries` e dispara mensagem privada via Evolution API para os professores que possuírem WhatsApp cadastrado.
* **Atenção Técnica sobre o n8n v2.x**:
  * Em versões 2.x do n8n, os nós `Schedule Trigger` devem utilizar estritamente `cronExpression` direta (evitando intervalos `weeks` que causam descarte silencioso de execução).
  * Qualquer alteração programática no banco SQLite do n8n deve sincronizar tanto a tabela `workflow_entity` quanto a tabela `workflow_history` usando o script [`scripts/manage_n8n.py`](file:///c:/Projetos/escola_agenda/scripts/manage_n8n.py).

---

## 🔐 9. Variáveis de Ambiente (`.env`)

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

## 🚀 10. Fluxo Oficial de Desenvolvimento, Deploy e Manutenção

### 10.1. Onde Fazer Alterações
1. **Modificações de Código**: Sempre desenvolvidas no ambiente local (`c:\Projetos\escola_agenda`) na branch **`main`**.
2. **Testes Locais**: Execute os testes unitários e de integração antes de subir:
   ```powershell
   pytest
   ```
3. **Commit e Push**:
   ```bash
   git add .
   git commit -m "feat/fix: descrição clara da alteração"
   git push origin main
   ```

### 10.2. Deploy na VPS via SSH
Após o push para o GitHub, conecte-se à VPS e execute a atualização:

```bash
# 1. Conectar via SSH
ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63

# 2. Navegar até a pasta do projeto
cd ~/escola_agenda

# 3. Baixar as novidades da branch main
git pull origin main

# 4. Reconstruir a imagem Docker localmente e reiniciar os containers
docker compose build
docker compose up -d

# 5. Conferir status dos containers
docker compose ps
```

### 10.3. Comandos Úteis de Diagnóstico e Troubleshooting na VPS

* **Ver logs da aplicação Flask em tempo real**:
  ```bash
  docker logs agenda_app -f --tail 50
  ```
* **Ver logs do worker Celery**:
  ```bash
  docker logs escola_agenda-worker-1 -f --tail 50
  ```
* **Verificar integridade HTTP (Healthcheck)**:
  ```bash
  curl -I http://localhost:5000/health
  curl -I https://agendaricardo.com.br/health
  ```
* **Acessar o terminal interativo do PostgreSQL**:
  ```bash
  docker exec -it agenda_db psql -U agenda_user -d agenda_db
  ```
* **Reiniciar Nginx no Host**:
  ```bash
  sudo systemctl reload nginx
  ```
* **Verificar logs do cron de backups**:
  ```bash
  tail -n 30 /home/ubuntu/escola_agenda/backup_cron.log
  tail -n 30 /home/ubuntu/backup_r2.log
  ```
* **Listar backups remotos salvos no Cloudflare R2**:
  ```bash
  rclone ls r2:agenda-escola-backups
  ```
