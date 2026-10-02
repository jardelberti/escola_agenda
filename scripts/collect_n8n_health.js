// Run inside n8n with stdin; SQLite is read-only. No workflow execution or modification.
const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');
const { parse } = require(require.resolve('flatted', { paths: ['/usr/local/lib/node_modules/n8n'] }));
const WORKFLOW = 'agendaEscola0001';
const db = new DatabaseSync('/home/node/.n8n/database.sqlite', { readOnly: true });
db.exec('PRAGMA busy_timeout=3000');
db.exec('BEGIN');
const workflow = db.prepare('SELECT active, activeVersionId, settings FROM workflow_entity WHERE id=?').get(WORKFLOW);
const history = workflow?.activeVersionId && db.prepare('SELECT nodes, connections FROM workflow_history WHERE versionId=? AND workflowId=?').get(workflow.activeVersionId, WORKFLOW);
const nodes = history ? JSON.parse(history.nodes) : [];
const trigger = nodes.find(n => n.type === 'n8n-nodes-base.scheduleTrigger');
const timezone = JSON.parse(workflow?.settings || '{}').timezone || process.env.GENERIC_TIMEZONE || 'America/New_York';
const scheduleOk = !trigger?.disabled && timezone === 'America/Sao_Paulo' && trigger?.parameters?.rule?.interval?.some(i => i.field === 'cronExpression' && i.expression === '0 7 * * 1-5') === true;

function summary(row) {
  if (!row || !row.startedAt) return null;
  const stored = db.prepare('SELECT data, workflowData FROM execution_data WHERE executionId=?').get(row.id);
  let accepted = null, adminOnly = false;
  if (stored) {
    try {
      const result = parse(stored.data).resultData;
      const oldNodes = JSON.parse(stored.workflowData).nodes || [];
      const sending = oldNodes.filter(n => n.type === 'n8n-nodes-base.httpRequest' && String(n.parameters?.url || '').includes('/message/sendText/'));
      adminOnly = sending.length === 1 && sending[0].name === 'Enviar Resumo ao Admin';
      accepted = 0;
      for (const node of sending) {
        for (const run of result?.runData?.[node.name] || []) {
          if (run.error) continue;
          for (const batch of run.data?.main || []) {
            for (const item of batch || []) {
              // A response ID proves API acceptance, not recipient delivery.
              if (item.json?.key?.id && !item.json?.error) accepted++;
            }
          }
        }
      }
    } catch (_) { accepted = null; }
  }
  const date = row.startedAt.includes('T') ? row.startedAt : row.startedAt.replace(' ', 'T');
  return { started_at: /(?:Z|[+-]\d\d:\d\d)$/.test(date) ? date : date + 'Z',
    status: ['success', 'error', 'running', 'waiting', 'canceled', 'crashed', 'new'].includes(row.status) ? row.status : 'unknown',
    mode: ['trigger', 'manual', 'retry'].includes(row.mode) ? row.mode : 'other', accepted, admin_only: adminOnly };
}
const latest = db.prepare('SELECT id,status,mode,startedAt FROM execution_entity WHERE workflowId=? AND deletedAt IS NULL ORDER BY id DESC LIMIT 1').get(WORKFLOW);
const automatic = db.prepare("SELECT id,status,mode,startedAt FROM execution_entity WHERE workflowId=? AND mode='trigger' AND deletedAt IS NULL ORDER BY id DESC LIMIT 1").get(WORKFLOW);
const payload = { active: workflow?.active === 1 && !!history, schedule_ok: scheduleOk, latest: summary(latest), automatic: summary(automatic) };
db.exec('COMMIT'); db.close();
async function publish() {
  const key = fs.readFileSync('/home/node/.n8n/agenda-monitor-key', 'utf8').trim();
  const response = await fetch('https://agendaricardo.com.br/api/integrations/monitor/whatsapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Monitor-Key': key },
    body: JSON.stringify(payload), signal: AbortSignal.timeout(10000), redirect: 'error'
  });
  if (!response.ok) throw new Error('monitor');
  console.log('Monitoramento WhatsApp atualizado; nenhum fluxo disparado.');
}
if (process.argv.includes('--dry-run')) console.log(JSON.stringify(payload));
else publish().catch(() => { console.error('Falha no coletor WhatsApp; conferir acesso e disponibilidade.'); process.exitCode = 1; });
