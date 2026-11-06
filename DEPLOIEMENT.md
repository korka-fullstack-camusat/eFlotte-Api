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

## 8. Serveur où les ports 80 / 443 sont déjà utilisés

Si un autre proxy (nginx, Apache…) occupe déjà 80 / 443 et gère le HTTPS du domaine :

1. Dans `~/eFlotte-Api/.env` :
   ```
   SITE_ADDRESS=:80
   CADDY_HTTP_PORT=8050
   CADDY_HTTPS_PORT=8443
   ```
2. `docker compose -f docker-compose.prod.yml up -d --build`
   → la plateforme (site + `/api`) répond sur `http://127.0.0.1:8050`.
3. Dans l'autre proxy, faire pointer le domaine vers ce port. Exemple nginx :
   ```nginx
   location / {
       proxy_pass http://127.0.0.1:8050;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       client_max_body_size 40M;   # 6 photos de la checklist mobile
   }
   ```
   puis `sudo nginx -t && sudo systemctl reload nginx`.

Le port 8050 n'a pas besoin d'être ouvert dans le pare-feu / groupe de sécurité : seul l'autre proxy y accède.

## Commandes utiles

```bash
docker logs -f --tail 100 eflotte-api      # logs API
docker logs -f --tail 100 eflotte-caddy    # logs HTTP / certificats
docker exec -it eflotte-api python create_admin.py
```

## Application mobile : publier l'APK (page https://eflotte.camusatsn.com/app)

La page `/app` (front) propose le bouton « Télécharger l'application ». Le fichier est servi par Caddy
depuis le dossier `telechargements/` de ce dépôt sur le serveur (hors Git), sous le nom **`eflotte-camusat.apk`**.

1. Construire l’APK : dans `eFlotte-Mobile`, `npm run apk` (construction EAS + téléchargement de `eflotte-camusat.apk` dans le dossier du projet ; `npm run apk:dernier` pour reprendre la dernière construction).
2. Le copier sur le serveur :
   ```bash
   scp eflotte-xxx.apk utilisateur@serveur:/srv/www/htdocs/eflotte-api/telechargements/eflotte-camusat.apk
   ```
   (ou, sur le serveur : `curl -L -o /srv/www/htdocs/eflotte-api/telechargements/eflotte-camusat.apk "<lien EAS>"`)
3. La première fois seulement (nouveau dossier monté dans Caddy) :
   ```bash
   cd /srv/www/htdocs/eflotte-api && git pull && docker compose -f docker-compose.prod.yml up -d caddy
   ```
Pour une nouvelle version, remplacer `eflotte-camusat.apk` suffit : pas de redémarrage. Lien à partager : https://eflotte.camusatsn.com/app
