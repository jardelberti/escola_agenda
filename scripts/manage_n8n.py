import sqlite3
import json
import uuid
from datetime import datetime

DB_PATH = "/data/database.sqlite"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fix_agenda_workflow():
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM workflow_entity WHERE id = ?", ("agendaEscola0001",)).fetchone()
    if not row:
        print("Workflow agendaEscola0001 not found!")
        return

    nodes = json.loads(row["nodes"])
    for node in nodes:
        if node.get("type") == "n8n-nodes-base.scheduleTrigger":
            print("Encontrado scheduleTrigger no agendaEscola0001. Atualizando para Cron Expression à prova de falhas...")
            # Usando cronExpression explícito para 07:00 de segunda a sexta
            node["parameters"] = {
                "rule": {
                    "interval": [
                        {
                            "field": "cronExpression",
                            "expression": "0 7 * * 1-5"
                        }
                    ]
                }
            }

    new_nodes_json = json.dumps(nodes)
    new_static_data = json.dumps({})
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.000")
    
    cur.execute("""
        UPDATE workflow_entity 
        SET nodes = ?, staticData = ?, active = 1, updatedAt = ?
        WHERE id = ?
    """, (new_nodes_json, new_static_data, now, "agendaEscola0001"))
    conn.commit()
    print("Workflow agendaEscola0001 atualizado com sucesso!")
    conn.close()

def create_test_workflow(target_hour=7, target_minute=50):
    conn = get_db()
    cur = conn.cursor()
    wf_id = "testeJardel001"
    version_id = str(uuid.uuid4())
    
    # Monta cron para o horário de teste
    cron_expr = f"{target_minute} {target_hour} * * *"
    print(f"Configurando workflow de teste para disparar às {target_hour:02d}:{target_minute:02d} (cron: {cron_expr})")

    nodes = [
        {
            "parameters": {
                "rule": {
                    "interval": [
                        {
                            "field": "cronExpression",
                            "expression": cron_expr
                        }
                    ]
                }
            },
            "id": "trigger-teste",
            "name": f"Disparar às {target_hour:02d}:{target_minute:02d}",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [200, 300]
        },
        {
            "parameters": {
                "method": "POST",
                "url": "http://100.81.69.55:8085/message/sendText/agenda-escola",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {
                            "name": "apikey",
                            "value": "evolution_secret_homelab_ricardo_2026"
                        }
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={\n  \"number\": \"5547999283466\",\n  \"text\": \"🧪 *TESTE N8N AUTOMÁTICO* 🧪\\n\\nDisparo agendado executado com SUCESSO via cron do n8n!\\nHorário previsto: " + f"{target_hour:02d}:{target_minute:02d}" + "\\n\\nSe você recebeu isso, o agendador está 100% curado e operacional!\"\n}",
                "options": {}
            },
            "id": "http-send-teste",
            "name": "Enviar WhatsApp Teste",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [440, 300]
        }
    ]

    connections = {
        "Disparar às " + f"{target_hour:02d}:{target_minute:02d}": {
            "main": [
                [
                    {
                        "node": "Enviar WhatsApp Teste",
                        "type": "main",
                        "index": 0
                    }
                ]
            ]
        }
    }

    settings = {
        "executionOrder": "v1",
        "timezone": "America/Sao_Paulo",
        "saveManualExecutions": True,
        "saveSuccessfulExecutions": True,
        "saveExecutionProgress": True
    }

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.000")

    # Verifica se já existe
    cur.execute("DELETE FROM workflow_history WHERE workflowId = ?", (wf_id,))
    cur.execute("DELETE FROM workflow_entity WHERE id = ?", (wf_id,))
    
    cur.execute("""
        INSERT INTO workflow_history (
            versionId, workflowId, authors, createdAt, updatedAt, nodes, connections, name
        ) VALUES (?, ?, 'Jardel Berti', ?, ?, ?, ?, ?)
    """, (
        version_id,
        wf_id,
        now,
        now,
        json.dumps(nodes),
        json.dumps(connections),
        "🧪 Teste WhatsApp Jardel - Agendamento"
    ))

    cur.execute("""
        INSERT INTO workflow_entity (
            id, name, active, nodes, connections, settings, staticData,
            versionId, activeVersionId, triggerCount, isArchived, versionCounter,
            createdAt, updatedAt
        ) VALUES (?, ?, 1, ?, ?, ?, '{}', ?, ?, 1, 0, 1, ?, ?)
    """, (
        wf_id,
        "🧪 Teste WhatsApp Jardel - Agendamento",
        json.dumps(nodes),
        json.dumps(connections),
        json.dumps(settings),
        version_id,
        version_id,
        now,
        now
    ))

    cur.execute("DELETE FROM shared_workflow WHERE workflowId = ?", (wf_id,))
    cur.execute("""
        INSERT INTO shared_workflow (
            workflowId, projectId, role, createdAt, updatedAt
        ) VALUES (?, 'zHc2RVlHaYlpzJir', 'workflow:owner', ?, ?)
    """, (wf_id, now, now))

    conn.commit()
    print(f"Workflow de teste {wf_id} inserido com sucesso!")
    conn.close()

if __name__ == "__main__":
    import sys
    fix_agenda_workflow()
    
    # Se passado minuto e hora via argumento
    h = 7
    m = 50
    if len(sys.argv) > 2:
        h = int(sys.argv[1])
        m = int(sys.argv[2])
    elif len(sys.argv) > 1:
        m = int(sys.argv[1])
    create_test_workflow(h, m)
