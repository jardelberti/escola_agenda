#!/bin/bash
# ==============================================================================
# Script de Backup Automatizado do PostgreSQL para Cloudflare R2
# Projeto: Agenda Escolar (agendaricardo.com.br)
# ==============================================================================
set -e

PROJECT_DIR="/home/ubuntu/escola_agenda"
BACKUP_DIR="${PROJECT_DIR}/data/backups"
R2_REMOTE="r2:agenda-escola-backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="backup_agenda_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"
LOG_FILE="/home/ubuntu/backup_r2.log"

mkdir -p "$BACKUP_DIR"

echo "==========================================================" >> "$LOG_FILE"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Iniciando backup para Cloudflare R2..." >> "$LOG_FILE"

# 1. Gera o dump do banco PostgreSQL dentro do container agenda_db compactado via gzip
docker exec -t agenda_db pg_dump -U agenda_user -d agenda_db --clean --if-exists | gzip > "$FILEPATH"

FILESIZE=$(ls -lh "$FILEPATH" | awk '{print $5}')
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Dump gerado com sucesso: $FILENAME ($FILESIZE)" >> "$LOG_FILE"

# 2. Envia para o Cloudflare R2
/usr/bin/rclone copyto --no-modtime "$FILEPATH" "${R2_REMOTE}/${FILENAME}"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Upload para Cloudflare R2 concluído com sucesso!" >> "$LOG_FILE"

# 3. Retenção na nuvem: remove arquivos com mais de 30 dias no R2
/usr/bin/rclone delete --min-age 30d "${R2_REMOTE}" >> "$LOG_FILE" 2>&1

# 4. Retenção local na VPS: remove backups temporários locais com mais de 7 dias
find "$BACKUP_DIR" -type f -name "backup_agenda_*.sql.gz" -mtime +7 -delete

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Rotina de backup finalizada com sucesso." >> "$LOG_FILE"
