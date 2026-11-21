# Paris Foot : mode d'emploi de l'installation

Tu fais cette installation **une seule fois**, en environ 30 minutes.
Ensuite tout tourne tout seul, et tu n'utilises plus que l'appli sur ton téléphone.

L'idée en une phrase : GitHub, un site gratuit, va servir de « bureau » à tes agents.
Ils y travaillent chaque jour à 7h et 17h, et y publient ton application.

---

## Étape 1 — Créer 2 clés gratuites (10 min)

Une « clé », c'est un mot de passe qui autorise tes agents à lire des données.

1. **football-data.org** : clique sur « Register », entre ton e-mail. Ta clé arrive par e-mail.
2. **the-odds-api.com** : clique sur « Get API key », choisis le plan gratuit (*Starter*). Ta clé arrive par e-mail.

Garde les deux e-mails ouverts, tu en auras besoin à l'étape 3.

## Étape 2 — Créer ton bureau GitHub (10 min, depuis un ordinateur de préférence)

1. Va sur **github.com** et crée un compte.
2. En haut à droite, « + », puis **New repository**.
   - Nom : `paris-foot`
   - Coche **Public** (sinon la page de l'appli n'est pas gratuite ; tes clés, elles, restent secrètes)
   - Clique sur **Create repository**.
3. Clique sur le lien **uploading an existing file**.
4. Dézippe le fichier que Claude t'a donné, ouvre le dossier `paris-foot`, sélectionne **tout son contenu**
   et glisse-le dans la page. Clique sur **Commit changes**.
   ⚠️ Vérifie que le dossier `.github` est bien envoyé (il est parfois caché). En cas de doute, demande à Claude.

## Étape 3 — Ranger les clés au coffre (3 min)

Dans ton dépôt : **Settings**, puis **Secrets and variables**, puis **Actions**, puis **New repository secret**.

| Nom (à recopier exactement) | Valeur |
|---|---|
| `FOOTBALL_DATA_KEY` | la clé reçue de football-data.org |
| `ODDS_API_KEY` | la clé reçue de the-odds-api.com |

## Étape 4 — Allumer l'application (2 min)

**Settings**, puis **Pages**. Dans « Branch », choisis `main` et le dossier `/docs`, puis **Save**.

Ton appli sera à l'adresse : **https://TON-PSEUDO.github.io/paris-foot/**

## Étape 5 — Premier lancement (5 min)

Onglet **Actions**, puis « Agents paris foot », puis **Run workflow**, puis le bouton vert.
Attends que le rond devienne une coche verte (environ 5 minutes la première fois). Ouvre ton appli : c'est prêt.

## Étape 6 — L'appli sur ton téléphone

- **iPhone** : ouvre l'adresse dans Safari, touche Partager, puis « Sur l'écran d'accueil ».
- **Android** : ouvre-la dans Chrome, menu ⋮, puis « Ajouter à l'écran d'accueil ».

## Étape 7 — L'agent presse (avec Claude)

Reviens dans la conversation avec Claude et dis : « Mon dépôt GitHub paris-foot est prêt ».
Claude connectera l'agent presse, qui lira la presse locale chaque matin à 9h.

---

## Ce qui tourne, et quand

| Heure (Suisse) | Qui | Quoi |
|---|---|---|
| 7h | 16 agents calculateurs | Matchs, cotes, Elo, xG, stats, forme, fatigue, enjeu, juge, pièges, conseils |
| 9h | Agent presse (Claude) | Presse locale des matchs du jour qui ont un conseil |
| 17h | Agent cotes | Second relevé des cotes : mouvements et cote de clôture |
| Lundi | Testeur | Examen du système sur les 3 saisons passées |

Coût : 0 CHF. Seul l'agent presse utilise ton abonnement Claude Pro (une recherche par matin).
