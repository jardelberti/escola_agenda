<div align="center">
  <img src="https://raw.githubusercontent.com/user-attachments/assets/1569a7c3-30b0-4a37-b952-4752b75a40b9" width="150px" />
  <h1>Agenda Escolar</h1>
  <p><strong>Sistema completo de agendamento de recursos para ambientes escolares, conteinerizado com Docker.</strong></p>
  <p>
    <a href="#">
      <img alt="Versão" src="https://img.shields.io/badge/version-1.6.0-blue?style=for-the-badge&logo=appveyor">
    </a>
    <a href="#">
      <img alt="Licença" src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge">
    </a>
    <a href="#">
      <img alt="Cloudflare R2" src="https://img.shields.io/badge/Backup-Cloudflare%20R2-F38020?style=for-the-badge&logo=cloudflare">
    </a>
    <a href="#">
      <img alt="WhatsApp & n8n" src="https://img.shields.io/badge/WhatsApp-Integrado-25D366?style=for-the-badge&logo=whatsapp">
    </a>
  </p>
</div>

## 📖 Sobre o Projeto

A **Agenda Escolar** é uma aplicação web desenvolvida em Python com o framework Flask, projetada para simplificar a reserva e o gerenciamento de recursos compartilhados (como salas de informática, salas multimídia, projetores e equipamentos) em escolas.

O sistema possui uma interface administrativa avançada com dashboard analítico e uma área intuitiva e responsiva para que professores consultem e reservem recursos com facilidade no computador ou smartphone.

* 🌐 **Produção Oficial**: [https://agendaricardo.com.br](https://agendaricardo.com.br)
* 🏫 **Instituição**: EMEB Prof. Ricardo Hoffmann
* 🤖 **Guia de Arquitetura & Manutenção**: Veja o arquivo [`AGENTS.md`](./AGENTS.md) para detalhes de infraestrutura, VPS e automações.

---

## 🌿 Branches do Projeto

| Branch | Finalidade | Status |
|---|---|---|
| **`main`** | Versão oficial mono-tenant em produção no `agendaricardo.com.br`. | **Ativa** |
| **`v2-comercial`** | Versão SaaS multi-tenant comercial (Stripe, Super Admin, Multi-Escolas). | **Standby** |

---

## ✨ Funcionalidades Principais

### 📊 Painel de Administração
* **Dashboard Analítico com Gráficos (Chart.js):** Indicadores em tempo real de ocupação semanal, ranking de recursos mais utilizados, distribuição por turno e métricas de utilização.
* **Gestão de Professores:** Cadastro, número de WhatsApp para lembretes e opção de **Ativar/Desativar** professores mantendo 100% do histórico preservado.
* **Gestão de Recursos com Múltiplas Unidades:** Suporte a capacidade unitária (ex.: 2 ou mais Projetores simultâneos no mesmo horário) e botão de **Pausar/Reativar** agendamentos sem apagar dados.
* **Ordenação Inteligente:** Reorganização dos recursos na tela inicial via "arrastar e soltar" (drag-and-drop).
* **Agenda Semanal Completa:** Grid responsivo com colunas alinhadas e filtros por turno (Matutino / Vespertino).
* **Governança & Controle de Uso:**
    * **Cota Semanal de Reservas:** Limite configurável de agendamentos por professor por semana para distribuição justa.
    * **Auditoria de Cancelamentos:** Histórico completo com autor, data/hora e justificativa de cancelamentos.
* **Relatórios e Exportação:** Visualização de métricas e download em **CSV / Excel** formatado (`utf-8-sig`, separador `;`).
* **Backup e Restauração:**
    * Backup e restore assíncronos no painel via Celery + Redis.
    * **Backup Automatizado Offsite:** Envio diário dos dumps compactados (`.sql.gz`) para o **Cloudflare R2** com política de retenção via Rclone.

---

### 👨‍🏫 Área do Professor & Agendamentos
* **Login Simplificado:** Acesso rápido utilizando apenas o número de matrícula.
* **Experiência Mobile Otimizada:**
    * **Régua Semanal de Datas:** Navegação tátil e intuitiva entre dias úteis na tela do smartphone.
    * **Seletores Táteis de Turno:** Alternância rápida entre turnos Matutino e Vespertino.
* **Agendamento em Lote & Rápido:** Seleção de múltiplos horários e turnos com confirmação em lote.
* **Detalhes da Reserva:** Campo dedicado para registrar a **Turma** atendida (ex.: 6º A, 9º B) e **Observações pedagógicas**.
* **Bloqueio de Agendamento Retroativo:** Professores só agendam datas a partir do dia atual (administradores mantêm permissão para ajustes de histórico).
* **Meus Agendamentos & Auto-Cadastro de WhatsApp:** O professor gerencia suas reservas e pode atualizar seu número de WhatsApp para receber alertas automáticos.

---

### 🔔 Notificações em Tempo Real & WhatsApp
* **Notificações Sonoras e Visuais no Navegador:** Alerta com som de sino e avisos na tela quando novas reservas são efetuadas, sem necessidade de atualizar a página manualmente.
* **Integração WhatsApp & n8n (`/api/integrations/daily-summary`):**
    * Disparo matinal automático de lembretes via n8n e Evolution API às **07:00** de segunda a sexta-feira.
    * **Separação por Turnos:** Mensagens formatadas agrupando os agendamentos em **☀️ Matutino** e **🌤️ Vespertino**.
    * **Resumo Geral para o Admin:** Panorama consolidado de todas as reservas do dia.
    * **Lembretes Individuais para Professores:** Mensagem direta no WhatsApp com os horários e salas agendados para o dia.

---

### 🛡️ Segurança e Arquitetura
* **Administradores:** matrícula e senha obrigatórias, com opção de manter o dispositivo conectado por sete dias. Operações críticas pedem confirmação recente; a página Segurança permite trocar a senha e sair de todos os dispositivos.
* **Recuperação:** link privado de uso único, válido por 30 minutos, gerado por outro administrador autenticado ou pelo responsável via SSH. Saber a matrícula não permite definir uma senha.
* **Proteção CSRF Global:** Validação em todos os formulários e chamadas assíncronas com `Flask-WTF`.
* **Modularização em Blueprints:** Código desacoplado e escalável dividido em `auth`, `agenda`, `admin` e `integrations`.
* **Healthcheck & Monitoramento:** Endpoint `/health` para monitoramento contínuo dos containers Docker.

---

## 🛠️ Tecnologias Utilizadas

* **Backend:** Python 3.11, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Migrate, Flask-WTF, Celery
* **Frontend:** HTML5, Tailwind CSS, Bootstrap Icons, SortableJS, Chart.js
* **Banco de Dados:** PostgreSQL 17 (produção) / SQLite (desenvolvimento)
* **Armazenamento em Nuvem:** Cloudflare R2 (backups offsite via Rclone)
* **Mensageria & Fila:** Redis
* **Containerização:** Docker & Docker Compose
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
* Professores entram por matrícula; administradores precisam também de senha e podem lembrar o dispositivo por sete dias.
* Para criar ou recuperar a senha administrativa, execute pelo acesso confiável ao servidor: `docker compose exec -T app flask auth access-link 7363`. Abra o link privado gerado e escolha sua senha; ele expira em 30 minutos e funciona uma única vez.
* Em desenvolvimento HTTP local, configure `COOKIE_SECURE=false` e `PUBLIC_BASE_URL=http://localhost:5000` no `.env`. Em produção, mantenha HTTPS e cookies seguros.
