#!/usr/bin/env bash
# Sauvegarde de la base eFlotte (rapports et photos compris).
# Garde les 14 dernières. À lancer chaque nuit par cron :
#   0 2 * * * /home/ubuntu/eFlotte-Api/deploy/sauvegarde.sh >> /home/ubuntu/sauvegardes/sauvegarde.log 2>&1
set -euo pipefail

DOSSIER="${DOSSIER_SAUVEGARDES:-$HOME/sauvegardes}"
GARDER="${GARDER:-14}"
mkdir -p "$DOSSIER"

FICHIER="$DOSSIER/eflotte-$(date +%Y-%m-%d_%H%M).sql.gz"
docker exec eflotte-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$FICHIER"
echo "$(date '+%F %T') sauvegarde : $FICHIER ($(du -h "$FICHIER" | cut -f1))"

# Supprime les plus anciennes au-delà de $GARDER
ls -1t "$DOSSIER"/eflotte-*.sql.gz | tail -n +$((GARDER + 1)) | xargs -r rm --
