# Usar uma imagem oficial do Python como base
FROM python:3.10-slim

# Definir o diretório de trabalho dentro do container
WORKDIR /app

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instalar as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Comando para inicializar o banco de dados (será executado manualmente na primeira vez)
# E o comando para rodar a aplicação, expondo na rede interna do container
CMD ["flask", "run", "--host=0.0.0.0"]