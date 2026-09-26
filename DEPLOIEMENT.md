# Déploiement eFlotte sur AWS EC2

Architecture (une seule EC2, Docker) :

```
Internet ──80/443──▶ Caddy ─┬─ /api, /docs ─▶ API (gunicorn) ─▶ PostgreSQL
                            └─ le reste ────▶ Front (Nginx, build Vite)
```

- `eFlotte-Api/docker-compose.prod.yml` : PostgreSQL + API + Caddy (crée le réseau Docker `eflotte`)
- `eFlotte-Front/docker-compose.prod.yml` : front de production (rejoint le réseau `eflotte`)
- Seuls les ports 80 et 443 sont ouverts ; la base écoute sur 127.0.0.1 uniquement.

## 1. Préparer le serveur (Ubuntu 24.04)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER      # puis se déconnecter / reconnecter
```

Sur une `t3.micro` / `t3.small`, ajouter de la mémoire d'échange (le build du front en a besoin) :

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Récupérer le code

```bash
cd ~
git clone https://github.com/korka-fullstack-camusat/eFlotte-Api.git
git clone https://github.com/korka-fullstack-camusat/eFlotte-Front.git
```

## 3. Configurer

```bash
cd ~/eFlotte-Api
cp .env.example .env
nano .env
```

- `POSTGRES_PASSWORD` : mot de passe fort (`openssl rand -hex 24`)
- `SECRET_KEY` : clé longue (`openssl rand -hex 50`)
- `SITE_ADDRESS=:80` pour commencer par l'IP ; un nom de domaine ensuite pour le HTTPS

## 4. Lancer

```bash
cd ~/eFlotte-Api   && docker compose -f docker-compose.prod.yml up -d --build
cd ~/eFlotte-Front && docker compose -f docker-compose.prod.yml up -d --build
docker ps
```

Attendus : `eflotte-db`, `eflotte-api` (healthy), `eflotte-caddy`, `eflotte-front`.

Ouvrir `http://<IP>` → connexion `admin` / `admin123`, **à changer immédiatement**
(ou créer son compte : `docker exec -it eflotte-api python create_admin.py`).

## 5. Mettre à jour après un changement de code

```bash
cd ~/eFlotte-Api   && git pull && docker compose -f docker-compose.prod.yml up -d --build
cd ~/eFlotte-Front && git pull && docker compose -f docker-compose.prod.yml up -d --build
```

## 6. Sauvegardes automatiques (chaque nuit à 2 h, 14 conservées)

```bash
crontab -e
# ajouter la ligne :
0 2 * * * /home/ubuntu/eFlotte-Api/deploy/sauvegarde.sh >> /home/ubuntu/sauvegardes/sauvegarde.log 2>&1
```

Restaurer une sauvegarde :

```bash
gunzip -c ~/sauvegardes/eflotte-AAAA-MM-JJ_HHMM.sql.gz | docker exec -i eflotte-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

## 7. Passer en HTTPS (nom de domaine)

1. Chez le fournisseur du domaine : enregistrement **A** → IP de l'EC2.
2. Dans `~/eFlotte-Api/.env` : `SITE_ADDRESS=eflotte.mondomaine.com`
3. `cd ~/eFlotte-Api && docker compose -f docker-compose.prod.yml up -d`

Caddy obtient et renouvelle le certificat tout seul (ports 80 et 443 ouverts).

## Commandes utiles

```bash
docker logs -f --tail 100 eflotte-api      # logs API
docker logs -f --tail 100 eflotte-caddy    # logs HTTP / certificats
docker exec -it eflotte-api python create_admin.py
```
