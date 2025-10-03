import smtplib
import os
from dotenv import load_dotenv  # 1. Importe a biblioteca

load_dotenv() 

# --- INFORMAÇÕES DE CONEXÃO ---
# Pegue sua API Key do SendGrid e cole aqui
API_KEY = os.environ.get('MAIL_PASSWORD')
SMTP_SERVER = os.environ.get('MAIL_SERVER')
SMTP_PORT = int(os.environ.get('MAIL_PORT', 587))
USERNAME = os.environ.get('MAIL_USERNAME')

# --- Endereços de Teste ---
FROM_EMAIL = os.environ.get('MAIL_DEFAULT_SENDER')
TO_EMAIL = "jardelberti@gmail.com"

print(f"Tentando se conectar a {SMTP_SERVER} na porta {SMTP_PORT}...")

try:
    # 1. Conecta ao servidor
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    print("Conexão inicial estabelecida.")

    # 2. Inicia a criptografia (TLS)
    server.starttls()
    print("Conexão segura (TLS) iniciada.")

    # 3. Faz o login
    server.login(USERNAME, API_KEY)
    print("Login realizado com sucesso.")

    # 4. Monta a mensagem (COM A CORREÇÃO)
    subject = "Teste de Conexão Direta"
    body = "Se você recebeu este e-mail, a conexão SMTP com Python funcionou!"

    # --- CORREÇÃO AQUI: Adicionando os cabeçalhos From e To ---
    message = f"""From: Agenda Escolar <{FROM_EMAIL}>
To: {TO_EMAIL}
Subject: {subject}

{body}"""

    # 5. Envia o e-mail (codificado em utf-8)
    server.sendmail(FROM_EMAIL, TO_EMAIL, message.encode('utf-8'))
    print(f"E-mail de teste enviado com sucesso para {TO_EMAIL}!")

except Exception as e:
    print(f"\n--- ERRO INESPERADO ---")
    print(f"Ocorreu um erro: {e}")
    print("--------------------")

finally:
    # 6. Fecha a conexão
    try:
        server.quit()
        print("Conexão fechada.")
    except NameError:
        pass
