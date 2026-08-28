# 🤖 Guia de Contexto do Projeto - Agenda Escolar

> **IMPORTANTE PARA AGENTES DE IA:**  
> Leia este documento antes de realizar qualquer alteração no repositório ou infraestrutura.

---

## 📌 1. Visão Geral do Projeto
Sistema de agendamento de recursos escolares (Sala de Informática, Sala Multimídia, Projetores, etc.) utilizado diariamente para gestão de horários escolares.

* **Domínio de Produção**: [https://agendaricardo.com.br](https://agendaricardo.com.br)
* **Repositório GitHub**: [https://github.com/jardelberti/escola_agenda](https://github.com/jardelberti/escola_agenda)
* **Registro de Containers**: **Build 100% local via Docker Compose na VPS** (o repositório no Docker Hub foi descontinuado/deletado para manter o GitHub como fonte única da verdade).

---

## 🌿 2. Estrutura de Branches no GitHub

Existem **apenas duas branches oficiais** no repositório:

| Branch | Finalidade | Descrição |
|---|---|---|
| **`main`** | **Produção Oficial (Ativa)** | Versão estável mono-tenant rodando em produção no `agendaricardo.com.br`. Possui gerenciamento de professores, agendamento por turnos, fechamento de horários, relatórios com gráficos, backup/restore PostgreSQL e a funcionalidade de **pausar/ativar recursos sem excluir dados**. |
| **`v2-comercial`** | **Versão Comercial 2.0 (Em Standby)** | Versão SaaS multi-tenant (`Escola`, `Usuario`, `Plano`, `Assinatura`, Stripe, Super Admin, autenticação Google OAuth). **Não está em uso no momento**, mas está preservada. |

---

## 🖥️ 3. Infraestrutura e Servidor de Produção

* **Provedor**: Oracle Cloud Infrastructure (OCI) - VM Always Free Tier (Ubuntu).
* **IP do Servidor**: `163.176.251.63`
* **DNS & SSL**: Cloudflare Proxy gerenciando `agendaricardo.com.br`.
* **Acesso SSH**:
  ```bash
  ssh -i C:\Users\monit\Downloads\ssh-key\ssh-key-agendaricardo.key ubuntu@163.176.251.63
  ```
* **Diretório do Projeto no Servidor**: `/home/ubuntu/escola_agenda`

---

## 🐳 4. Containers Docker em Produção

A stack de produção roda via Docker Compose compilada localmente a partir do código do GitHub:

| Container | Imagem Local | Função |
|---|---|---|
| `agenda_app` | `jardelberti/agenda.escola:v1.1` | Aplicação web Flask (Gunicorn, 2 workers na porta 5000) |
| `escola_agenda-worker-1` | `jardelberti/agenda.escola:v1.1` | Worker Celery para tarefas em background (pg_restore) |
| `agenda_db` | `postgres:17-alpine` | Banco de dados PostgreSQL (Volume: `postgres_data`) |
| `agenda_redis` | `redis:alpine` | Fila de mensagens do Celery (Volume: `redis_data`) |

---

## 📦 5. Onde o Código e as Versões Vivem

1. **No seu PC (`c:\Projetos\escola_agenda`)**:
   - Branch ativa: **`main`** (Versão oficial de produção atualizada com recurso de pausar agendamento).
   - Branch alternativa: **`v2-comercial`** (Versão 2.0 multi-tenant preservada).
2. **No GitHub (`https://github.com/jardelberti/escola_agenda`)**:
   - **`main`**: Versão oficial de produção ativa.
   - **`v2-comercial`**: Versão comercial em standby.
3. **No Docker Hub**:
   - *Desativado / Deletado*. Não há dependência de registry externo.
4. **No Servidor de Produção (VPS Oracle)**:
   - Sincronizado com a branch **`main`** do GitHub.
   - Imagem compilada localmente via `docker compose build`.

---

## 🛠️ 6. Comandos Úteis de Manutenção

### No Servidor via SSH:
```bash
# Entrar na pasta do projeto
cd ~/escola_agenda

# Atualizar com a versão mais recente do GitHub
git pull origin main

# Reconstruir e reiniciar containers
docker compose build
docker compose up -d

# Ver status dos containers
docker compose ps

# Ver logs da aplicação Flask
docker logs agenda_app -f --tail 50

# Reiniciar aplicação
docker compose restart app worker

# Acessar o banco de dados PostgreSQL
docker exec -it agenda_db psql -U agenda_user -d agenda_db
```

### Pausar / Reativar Recurso via Painel ou SQL:
- **Pelo Painel**: Acesse `https://agendaricardo.com.br/admin` e clique no botão **Pausar** ou **Ativar** ao lado do recurso.
- **Pelo SQL**:
  ```sql
  -- Pausar Sala Multimídia (ID 2):
  UPDATE resource SET is_active = FALSE WHERE id = 2;

  -- Reativar Sala Multimídia:
  UPDATE resource SET is_active = TRUE WHERE id = 2;
  ```
