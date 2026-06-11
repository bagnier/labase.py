## cadre général

- une base pour toute application pro / Saas
- fondée sur Supabase
- en Python moderne


## buts

### technique

- [x] uv
- [x] python 3.14
- [x] fastAPI
- [x] pytest
- [x] séparation en apps
- [x] BDD dual driver, Json & Web
- [x] SSR HTMX
- [x] migrations database
- [ ] collaboration par hooks entre les apps
- [x] CORS
- [x] headers de sécurité (HSTS, CSP)
- [x] healthcheck (liveness / readiness)
- [x] rate-limiting
- [x] logging
- [x] observabilité
- [x] TLS and HTTP/2
- [x] OWASP Dependency Check
- [ ] file de tâches asynchrones
- [ ] index fulltext
- [ ] cache
- [ ] messaging
- [ ] email
- [ ] doc déploiement prod (secrets, env)


### fonctionnel

- [x] authentification
- [x] création de compte
- [x] creation d'organisation
- [x] partage de l'ownership d'organisation
- [x] ajout et revocation de membres
- [x] invitations par token (accept flow)
- [x] todo list comme exemple CRUD
- [x] gestion de fichiers (bucket + share tokens)
- [ ] flashcards comme exemple HexArch
- [ ] dashboard user (contexte testé mais router non câblé dans main.py)
- [ ] admin dashboard
