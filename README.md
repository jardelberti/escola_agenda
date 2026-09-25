<div align="center">
  <img src="https://raw.githubusercontent.com/user-attachments/assets/1569a7c3-30b0-4a37-b952-4752b75a40b9" width="150px" />
  <h1>Agenda Escolar</h1>
  <p><strong>Um sistema completo de agendamento de recursos para ambientes escolares, conteinerizado com Docker.</strong></p>
  <p>
    <a href="#">
      <img alt="Versão" src="https://img.shields.io/badge/version-1.2.0-blue?style=for-the-badge&logo=appveyor">
    </a>
    <a href="#">
      <img alt="Licença" src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge">
    </a>
    <a href="#">
      <img alt="Cloudflare R2" src="https://img.shields.io/badge/Backup-Cloudflare%20R2-F38020?style=for-the-badge&logo=cloudflare">
    </a>
  </p>
</div>

## 📖 Sobre o Projeto

A **Agenda Escolar** é uma aplicação web desenvolvida em Python com o framework Flask, projetada para simplificar o agendamento de recursos compartilhados (como salas de informática, laboratórios multimídia, projetores e equipamentos) em escolas.

O sistema possui uma interface administrativa para gestão completa e uma área simples para professores consultarem horários e agendarem recursos.

* 🌐 **Produção Oficial**: [https://agendaricardo.com.br](https://agendaricardo.com.br)
* 🤖 **Guia de Arquitetura para IAs**: Veja o arquivo [`AGENTS.md`](./AGENTS.md) para detalhes de infraestrutura, VPS e manutenção.

---

## 🌿 Branches do Projeto

| Branch | Finalidade | Status |
|---|---|---|
| **`main`** | Versão oficial mono-tenant em produção no `agendaricardo.com.br`. | **Ativa** |
| **`v2-comercial`** | Versão SaaS multi-tenant comercial (Stripe, Super Admin, Escolas). | **Standby** |

---

## ✨ Funcionalidades Principais

* **Painel de Administração:**
    * Gerenciamento de usuários (professores e administradores).
    * Cadastro, edição e exclusão de recursos (salas, equipamentos).
    * **Pausar/Reativar agendamento de recursos** sem apagar histórico ou configurações.
    * Configuração de grades de horários personalizadas (matutino/vespertino).
    * **Agenda Semanal Completa:** Grid responsivo com colunas alinhadas e visualização por turno.
    * **Relatórios e Gráficos:** Métricas de ocupação e **exportação em CSV/Excel** (`utf-8-sig`, separador `;`).
    * **Backup e Restauração:**
        * Backup manual e restauração em segundo plano via Celery + Redis.
        * **Backup Automatizado Offsite:** Envio diário dos dumps compactados (`.sql.gz`) para o **Cloudflare R2** com política de retenção.
    * Ordenação de recursos na tela inicial via "arrastar e soltar" (drag-and-drop).
* **Área do Professor:**
    * Login simplificado utilizando apenas a matrícula.
    * Visualização interativa das agendas diárias por recurso.
    * Navegação inteligente entre os dias úteis (pulando finais de semana).
    * **Bloqueio de Agendamento Retroativo:** Professores só agendam datas a partir do dia atual (administradores mantêm permissão para ajustes de histórico).
    * Agendamento rápido de horários livres e gestão de "Meus Agendamentos".
* **Segurança e Arquitetura:**
    * **Proteção CSRF Global:** Validação automática com `Flask-WTF` em todos os formulários e chamadas assíncronas.
    * **Modularização em Blueprints:** Código desacoplado e escalável dividido em `auth`, `agenda` e `admin`.

---

## 🛠️ Tecnologias Utilizadas

* **Backend:** Python 3.11, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Migrate, Flask-WTF, Celery
* **Frontend:** HTML5, Tailwind CSS, Bootstrap Icons, SortableJS, Chart.js
* **Banco de Dados:** SQLite (desenvolvimento local) ou PostgreSQL 17 (produção)
* **Armazenamento em Nuvem:** Cloudflare R2 (backups offsite via Rclone)
* **Fila / Cache:** Redis
* **Containerização:** Docker Compose
* **Servidor WSGI:** Gunicorn

---

## 🚀 Como Executar com Docker Compose

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/jardelberti/escola_agenda.git
   cd escola_agenda
   ```

2. **Configure o arquivo `.env`:**
   ```bash
   cp .env.example .env
   ```

3. **Construa e inicie os containers:**
   ```bash
   docker compose up -d --build
   ```

4. **Acesse:** `http://localhost:5000`

---

## 🔑 Acesso Inicial

* **Matrícula do Administrador Padrão:** `7363` (Jardel)
