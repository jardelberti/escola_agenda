# Usar uma imagem oficial do Python como base
FROM python:3.11-slim

# Definir o diretório de trabalho dentro do container
WORKDIR /app

# Instalar gunicorn
RUN pip install gunicorn

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instalar as dependências da aplicação
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Expor a porta que o Gunicorn vai usar
EXPOSE 5000

# Variável de ambiente para indicar que estamos no Docker
ENV DOCKER_ENV=1

# Comando para rodar a aplicação com Gunicorn
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:5000", "app:app"]
