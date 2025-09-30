<div align="center">
  <h1>Agenda Escolar</h1>
  <p><strong>Um sistema completo de agendamento de recursos para ambientes escolares, conteinerizado com Docker.</strong></p>
  <p>
    <a href="#">
      <img alt="Versão" src="https://img.shields.io/badge/version-1.0.0-blue?style=for-the-badge&logo=appveyor">
    </a>
    <a href="#">
      <img alt="Licença" src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge">
    </a>
  </p>
</div>

## 📖 Sobre o Projeto

A **Agenda Escolar** é uma aplicação web robusta, desenvolvida em Python com o framework Flask, projetada para simplificar o agendamento de recursos compartilhados (como salas, laboratórios e equipamentos) em escolas.

O sistema possui uma interface administrativa para o gerenciamento completo e uma área para professores, que podem visualizar as agendas e realizar agendamentos de forma simples e intuitiva. A aplicação é flexível, podendo rodar tanto em um ambiente de desenvolvimento local com um banco de dados SQLite quanto em produção com Docker e um banco de dados PostgreSQL.

---

## ✨ Funcionalidades Principais

* **Painel de Administração:**
    * Gerenciamento de usuários (professores e administradores).
    * Cadastro, edição e exclusão de recursos (salas, equipamentos).
    * Configuração de grades de horários personalizadas (matutino/vespertino) para cada recurso.
    * Visualização de uma agenda semanal completa com todos os agendamentos.
    * Geração de relatórios de utilização por recurso e período.
    * Ordenação da exibição dos recursos na tela inicial através de "arrastar e soltar".
* **Área do Professor:**
    * Login simplificado utilizando apenas a matrícula.
    * Visualização clara das agendas diárias de cada recurso.
    * Navegação intuitiva entre os dias, pulando finais de semana.
    * Agendamento de horários livres com um clique.
    * Permissão para excluir apenas os seus próprios agendamentos.

---

## 🛠️ Tecnologias Utilizadas

* **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Migrate
* **Frontend:** HTML, Bootstrap 5, JavaScript
* **Banco de Dados:** SQLite (para desenvolvimento), PostgreSQL (para produção)
* **Containerização:** Docker, Docker Compose
* **Servidor de Produção:** Gunicorn

---

## 🚀 Como Executar o Projeto

Existem duas maneiras principais de rodar a aplicação: localmente para desenvolvimento ou utilizando Docker para uma implantação mais robusta.

### Método 1: Ambiente de Desenvolvimento Local

1.  **Pré-requisitos:**
    * Python 3.10 ou superior
    * Git

2.  **Clone o Repositório:**
    ```bash
    git clone [https://github.com/jardelberti/escola_agenda.git](https://github.com/jardelberti/escola_agenda.git)
    cd escola_agenda
    ```

3.  **Crie e Ative um Ambiente Virtual:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # No macOS/Linux
    .\venv\Scripts\Activate  # No Windows
    ```

4.  **Instale as Dependências:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Inicialize e Migre o Banco de Dados:**
    O Flask-Migrate gerencia a estrutura do banco. Execute estes comandos na primeira vez:
    ```bash
    # Cria a pasta de migrações (apenas uma vez)
    flask db init
    # Gera o script da primeira migração
    flask db migrate -m "Criação inicial das tabelas"
    # Aplica a migração, criando o banco de dados
    flask db upgrade
    ```

6.  **Crie o Usuário Administrador Padrão:**
    Execute o comando `seed-db` para popular o banco com o usuário inicial.
    ```bash
    flask seed-db
    ```

7.  **Rode a Aplicação:**
    ```bash
    flask run
    ```
    A aplicação estará acessível em `http://127.0.0.1:5000`.

### Método 2: Utilizando Docker (Recomendado para Produção)

1.  **Pré-requisitos:**
    * Docker
    * Docker Compose

2.  **Configure o Ambiente:**
    Crie um arquivo chamado `.env` na raiz do projeto. Copie e cole o conteúdo abaixo, ajustando os valores conforme sua necessidade.
    ```bash
    # Arquivo de configuração de ambiente

    # Credenciais do Banco de Dados PostgreSQL (se usar o compose)
    POSTGRES_USER=agenda_user
    POSTGRES_PASSWORD=agenda_password
    POSTGRES_DB=agenda_db

    # Porta que a aplicação irá usar no seu servidor (Host)
    HOST_PORT=5000

    # Nome da imagem Docker da sua aplicação
    APP_IMAGE=jardelberti/agenda.escola:latest
    ```

3.  **Inicie os Contêineres:**
    O Docker Compose irá construir a imagem, baixar as dependências e iniciar todos os serviços em segundo plano (`-d`).
    ```bash
    docker-compose up -d --build
    ```

4.  **Configure o Banco de Dados (Primeira Execução):**
    Aguarde um minuto para os serviços iniciarem e execute os comandos abaixo.
    * Para criar as tabelas:
        ```bash
        docker-compose exec app flask db upgrade
        ```
    * Para criar o usuário admin padrão:
        ```bash
        docker-compose exec app flask seed-db
        ```

5.  **Acesse a Aplicação:**
    A aplicação estará disponível no seu navegador em: `http://localhost:5000/` (ou a porta que você definiu em `HOST_PORT`).

---

## 🗄️ Configuração do Banco de Dados

A aplicação é projetada para ser flexível.

* **Padrão (SQLite):** Se nenhuma configuração for fornecida, ela criará um arquivo `agenda.db` na pasta do projeto, ideal para desenvolvimento.

* **Produção (PostgreSQL):** Para usar um banco de dados PostgreSQL (como o Amazon RDS), você precisa definir uma variável de ambiente chamada `DATABASE_URL`.

    **Formato da Variável:**
    ```
    DATABASE_URL=postgresql://USUARIO:SENHA@HOST:PORTA/NOME_DO_BANCO
    ```

    **Como usar com Docker Compose:**
    Adicione a variável ao seu arquivo `.env`. A aplicação irá priorizar a `DATABASE_URL` sobre as configurações `POSTGRES_*`.

---

## 🔑 Acesso Inicial

Após inicializar o banco de dados, um usuário administrador padrão é criado para o primeiro acesso. **O login requer apenas a matrícula.**

* **Nome:** `Jardel`
* **Matrícula:** `7363`

Use esta matrícula na tela de login para acessar o painel de administração e começar a configurar o sistema.
