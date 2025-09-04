# Usar uma imagem oficial do Python como base
FROM python:3.11-slim

# Definir o diretório de trabalho dentro do container
WORKDIR /app

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instalar as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Expor a porta que o Flask vai usar
EXPOSE 5000

# Comando para rodar a aplicação em modo de produção
# Gunicorn é um servidor web WSGI mais robusto que o servidor de desenvolvimento do Flask.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]