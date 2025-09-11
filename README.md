Agenda Escolar - Sistema de Agendamento de Recursos
📖 Sobre o Projeto
A Agenda Escolar é uma aplicação web desenvolvida em Python com o framework Flask, projetada para facilitar o agendamento de recursos compartilhados (como salas de aula, laboratórios e equipamentos) em um ambiente escolar.

O sistema possui uma interface administrativa para o gerenciamento completo e uma área para professores, que podem visualizar as agendas e realizar agendamentos de forma simples e intuitiva. A aplicação é flexível, podendo rodar tanto em um ambiente de desenvolvimento local com um banco de dados SQLite quanto em produção com Docker e um banco de dados PostgreSQL.

✨ Funcionalidades Principais
Painel de Administração:

Gerenciamento de usuários (professores e administradores).

Cadastro, edição e exclusão de recursos (salas, equipamentos).

Configuração de grades de horários personalizadas (matutino/vespertino) para cada recurso.

Visualização de uma agenda semanal completa com todos os agendamentos.

Geração de relatórios de utilização por recurso e período.

Ordenação da exibição dos recursos na tela inicial através de "arrastar e soltar".

Área do Professor:

Login simplificado utilizando apenas a matrícula.

Visualização clara das agendas diárias de cada recurso.

Navegação intuitiva entre os dias, pulando finais de semana.

Agendamento de horários livres com um clique.

Permissão para excluir apenas os seus próprios agendamentos.

🛠️ Tecnologias Utilizadas
Backend: Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Migrate

Frontend: HTML, Bootstrap 5, JavaScript

Banco de Dados: SQLite (para desenvolvimento), PostgreSQL (para produção)

Containerização: Docker, Docker Compose

Servidor de Produção: Gunicorn

🚀 Como Executar o Projeto
Existem duas maneiras principais de rodar a aplicação: localmente para desenvolvimento ou utilizando Docker para uma implantação mais robusta.

Método 1: Ambiente de Desenvolvimento Local
Pré-requisitos:

Python 3.10 ou superior

Git

Clone o Repositório:

git clone [https://github.com/seu-usuario/agenda-escola.git](https://github.com/seu-usuario/agenda-escola.git)
cd agenda-escola

Crie e Ative um Ambiente Virtual:

python -m venv venv
source venv/bin/activate  # No macOS/Linux
.\venv\Scripts\Activate  # No Windows

Instale as Dependências:

pip install -r requirements.txt

Inicialize e Migre o Banco de Dados:
O Flask-Migrate gerencia a estrutura do banco. Execute estes comandos na primeira vez:

# Cria a pasta de migrações (apenas uma vez)
flask db init
# Gera o script da primeira migração
flask db migrate -m "Criação inicial das tabelas"
# Aplica a migração, criando o banco de dados
flask db upgrade

Crie o Usuário Administrador Padrão:
Execute o comando seed-db para popular o banco com o usuário inicial.

flask seed-db

Rode a Aplicação:

flask run

A aplicação estará acessível em http://127.0.0.1:5000.

Método 2: Utilizando Docker (Recomendado para Produção)
Pré-requisitos:

Docker

Docker Compose

Construa a Imagem Docker:
Na raiz do projeto (onde está o docker-compose.yml), execute:

docker-compose build

Inicie o Container:
Este comando irá iniciar a aplicação em segundo plano.

docker-compose up -d

Crie e Popule o Banco de Dados:
Com o container rodando, execute estes comandos para criar as tabelas e o usuário admin.

# Aplica as migrações para criar as tabelas
docker-compose exec app flask db upgrade
# Popula o banco com o usuário padrão
docker-compose exec app flask seed-db

Acesse a Aplicação:
A aplicação estará acessível em http://localhost:8080.

🗄️ Configuração do Banco de Dados
A aplicação é projetada para ser flexível.

Padrão (SQLite): Se nenhuma configuração for fornecida, ela criará um arquivo agenda.db na pasta do projeto, ideal para desenvolvimento.

Produção (PostgreSQL): Para usar um banco de dados PostgreSQL (como o Amazon RDS), você precisa definir uma variável de ambiente chamada DATABASE_URL.

Formato da Variável:

DATABASE_URL=postgresql://USUARIO:SENHA@HOST:PORTA/NOME_DO_BANCO

Como usar com Docker Compose:
Você pode criar um arquivo .env na raiz do projeto e adicionar a linha acima, ou modificar o docker-compose.yml para incluir a variável de ambiente:

services:
  app:
    # ...
    environment:
      - DATABASE_URL=postgresql://user:pass@host:port/dbname

Matrícula padrão para acessar painel admin: 7363