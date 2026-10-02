import sqlite3
import json
import uuid
import sys
from datetime import datetime, timezone

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
        conn.close()
        return

    nodes = json.loads(row["nodes"])
    for node in nodes:
        # 1. Schedule Trigger fix
        if node.get("type") == "n8n-nodes-base.scheduleTrigger":
            print("Atualizando scheduleTrigger para Cron Expression direta: 0 7 * * 1-5")
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
        
        # 2. HTTP Request retry fix (para evitar falhas por instabilidade momentânea de DNS/rede)
        if node.get("type") == "n8n-nodes-base.httpRequest":
            print(f"Configurando retry automático no nó: {node.get('name')}")
            opts = node.get("parameters", {}).get("options", {})
            opts["retryOnFail"] = True
            opts["maxTries"] = 3
            opts["waitBetweenTries"] = 2000
            node["parameters"]["options"] = opts

    new_nodes_json = json.dumps(nodes)
    new_static_data = json.dumps({})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")
    active_version_id = row["activeVersionId"] or row["versionId"]

    # Atualiza workflow_entity
    cur.execute("""
        UPDATE workflow_entity 
        SET nodes = ?, staticData = ?, active = 1, updatedAt = ?
        WHERE id = ?
    """, (new_nodes_json, new_static_data, now, "agendaEscola0001"))

    # ATENÇÃO CRÍTICA: No n8n 2.x, a versão ativa executada é lida de workflow_history!
    # Atualiza workflow_history para refletir a nova versão
    hist_row = cur.execute("SELECT * FROM workflow_history WHERE workflowId = ? AND versionId = ?", 
                           ("agendaEscola0001", active_version_id)).fetchone()
    if hist_row:
        cur.execute("""
            UPDATE workflow_history
            SET nodes = ?, updatedAt = ?
            WHERE workflowId = ? AND versionId = ?
        """, (new_nodes_json, now, "agendaEscola0001", active_version_id))
        print(f"workflow_history atualizado para versão ativa {active_version_id}!")
    else:
        # Se não existia o registro histórico exato, cria
        cur.execute("""
            INSERT INTO workflow_history (
                versionId, workflowId, authors, createdAt, updatedAt, nodes, connections, name
            ) VALUES (?, 'agendaEscola0001', 'Jardel Berti', ?, ?, ?, ?, 'Agenda Escolar - Notificações WhatsApp')
        """, (active_version_id, now, now, new_nodes_json, row["connections"]))
        print(f"workflow_history inserido para versão {active_version_id}!")

    # Limpa workflow de teste antigo para não disparar mais
    cur.execute("DELETE FROM workflow_history WHERE workflowId = 'testeJardel001'")
    cur.execute("DELETE FROM shared_workflow WHERE workflowId = 'testeJardel001'")
    cur.execute("DELETE FROM workflow_entity WHERE id = 'testeJardel001'")
    print("Workflow de teste anterior limpo com sucesso.")

    conn.commit()
    print("Workflow agendaEscola0001 100% atualizado e alinhado!")
    conn.close()

def create_test_workflow(target_hour, target_minute):
    conn = get_db()
    cur = conn.cursor()
    wf_id = "testeJardel001"
    version_id = str(uuid.uuid4())
    
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
                "options": {
                    "retryOnFail": True,
                    "maxTries": 3,
                    "waitBetweenTries": 2000
                }
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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")

    cur.execute("DELETE FROM workflow_history WHERE workflowId = ?", (wf_id,))
    cur.execute("DELETE FROM workflow_entity WHERE id = ?", (wf_id,))
    cur.execute("DELETE FROM shared_workflow WHERE workflowId = ?", (wf_id,))

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

    cur.execute("""
        INSERT INTO shared_workflow (
            workflowId, projectId, role, createdAt, updatedAt
        ) VALUES (?, 'zHc2RVlHaYlpzJir', 'workflow:owner', ?, ?)
    """, (wf_id, now, now))

    conn.commit()
    print(f"Workflow de teste {wf_id} inserido com sucesso para às {target_hour:02d}:{target_minute:02d}!")
    conn.close()

if __name__ == "__main__":
    fix_agenda_workflow()
    
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        # Formato: --test HH MM
        h = int(sys.argv[2])
        m = int(sys.argv[3])
        create_test_workflow(h, m)
