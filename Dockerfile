# Estágio 1: Build - Instala dependências
FROM python:3.11-slim as builder

WORKDIR /usr/src/app

# Instala dependências de compilação que não são necessárias na imagem final
RUN apt-get update && apt-get install -y --no-install-recommends build-essential

# Copia e instala as dependências Python de forma otimizada
COPY requirements.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /usr/src/app/wheels -r requirements.txt

# Estágio 2: Final - A imagem que será usada em produção
FROM python:3.11-slim

WORKDIR /app

# Copia apenas as dependências pré-compiladas do estágio anterior
COPY --from=builder /usr/src/app/wheels /wheels
RUN pip install --no-cache /wheels/*

# Copia o código da aplicação (será feito pelo docker-compose ou manualmente no servidor)
COPY . .

# Expõe a porta que o Gunicorn vai usar
EXPOSE 5000

# Comando para iniciar a aplicação com Gunicorn (servidor de produção WSGI)
# --workers=3: Um bom ponto de partida para a maioria das VPS.
# --timeout 120: Aumenta o tempo de espera para requisições mais longas.
CMD ["gunicorn", "--workers=1", "--bind", "0.0.0.0:5000", "--timeout", "120", "app:app"]