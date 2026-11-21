# HighschoolRP CrowBot v2 — Mise à jour des familles officielles

Cette version **améliore le CrowBot existant**. Elle ne remplace pas le bot de créateurs de contenu.

## ⚠️ Installer sans perdre les familles existantes

1. **Arrête CrowBot** : ferme la fenêtre `START_WINDOWS.bat` ou arrête l'ancien service Railway. Ne lance **pas** deux CrowBots avec le même token.
2. **Fais une copie de sauvegarde** du dossier `data/` (notamment `data/families.sqlite3`) et de ton fichier `.env` dans un endroit sûr. Fais la sauvegarde après avoir arrêté le bot pour éviter un fichier SQLite incomplet.
3. Décompresse `HighschoolRP-CrowBot-v2-Moderation.zip`. Dans le dossier `HighschoolRP-CrowBot`, **remplace les fichiers du programme** de ton ancien CrowBot (notamment `bot.py`) par ceux du nouveau ZIP.
4. **Garde ton fichier `.env` existant et ton dossier `data/` existant**. Ne remplace pas la base SQLite par une base vide. Si `DATABASE_PATH` dans `.env` utilise un autre chemin, conserve précisément ce chemin.
5. Lance `START_WINDOWS.bat` comme avant. La nouvelle version ajoute automatiquement les colonnes et tables nécessaires dans la base existante.
6. Dans ton serveur Discord, crée deux salons texte publics : `#official-families` et `#family-blacklist`. Mets-les **en lecture seule pour les membres** et autorise le bot à envoyer des embeds, fichiers et messages ainsi qu'à lire l'historique. Évite de cacher ces salons au bot.
7. En tant qu'administrateur, utilise :

```text
/family-channels official_families:#official-families family_blacklist:#family-blacklist
```

Cela publie les familles **déjà approuvées** (migration des annonces) et construit la liste des familles blacklistées. **Tu n'as pas besoin de refaire `/family-setup`** si ta configuration précédente fonctionne.

8. Vérifie `/family-ping`, puis `/family-sync-boards` si tu dois republier les embeds.

Pour un déploiement Railway, remplace le code dans ton dépôt (sans inclure `.env`) et **conserve le volume `/data`** avec `DATABASE_PATH=/data/families.sqlite3` ; ne crée pas une base neuve par erreur.

## 📋 Commandes Discord (tous les noms et messages du bot sont en anglais)

| Commande | Personnes autorisées | Fonction |
|---|---|---|
| `/family-channels` | Administrateur / Manage Server | Choisir les salons d'annonces officielles et de blacklist |
| `/family-sync-boards` | Head of Families / administrateur | Republier ou mettre à jour les embeds publics, y compris les familles déjà existantes |
| `/family-whitelist-request` | Tout membre | Demander l'accès à la whitelist de modération |
| Boutons `Whitelist • Approve / Decline` | Head of Families / administrateur | Autoriser ou refuser une demande de whitelist dans `#family-reviews` |
| `/family-whitelist-list` | Head of Families / administrateur | Voir la whitelist et les demandes en attente |
| `/family-whitelist-revoke member:@User` | Head of Families / administrateur | Révoquer l'autorisation d'un utilisateur |
| `/family-whitelist-repost request_id:1` | Head of Families / administrateur | Reposter une demande si sa fiche a disparu |
| `/family-remove application_id:1 reason:... confirm:True` | **Whitelist approuvée**, Head ou administrateur | Retirer une famille officielle, supprimer ses rôles, ses 4 salons et sa fiche publique |
| `/family-remove-retry application_id:1` | Head / administrateur; ou whitelist si retrait simple | Reprendre une suppression interrompue par un manque de permissions ou un plantage |
| `/family-warn application_id:1 reason:...` | Head of Families / administrateur | Ajouter `Warn 1`, `Warn 2`, ... dans la fiche officielle et publier l'avertissement |
| `/family-warns application_id:1` | Tout membre | Afficher l'historique des avertissements, y compris les avertissements révoqués |
| `/family-unwarn application_id:1 warn_number:1 reason:...` | Head of Families / administrateur | Révoquer un avertissement, garder l'historique d'audit |
| `/family-blacklist application_id:1 reason:... confirm:True` | Head of Families / administrateur | Blacklister une famille officielle : retirer ses espaces et la publier dans le registre |
| `/family-blacklist-list` | Tout membre | Afficher un résumé des familles blacklistées |
| `/family-unblacklist application_id:1 reason:...` | Head of Families / administrateur | Retirer la famille de la liste noire, autoriser une nouvelle candidature |

Les anciennes commandes comme `/family-setup`, `/family-panel`, `/family-approve`, `/family-add`, `/family-kick` et `/family-directory` continuent de fonctionner.

## Comment marche l'approbation d'une famille ?

Quand le Head of Families approuve une candidature, les deux rôles et les 4 salons privés sont créés comme avant. En plus, le bot publie **un embed avec le logo HS** dans `#official-families` (nom, chef, région, groupe d'âge, couleur, membres déclarés, nombre de warns, ID). En cas de nouvel avertissement, cet embed est mis à jour.

## Whitelist = permission du bot, pas un rôle Discord

Un membre demande l'accès avec `/family-whitelist-request`. Le bot affiche une fiche privée dans ton salon **de review des familles**. Le Head of Families utilise **Approve** ou **Decline**. Une approbation donne uniquement le droit de supprimer **des familles officielles avec `/family-remove`**, pas de donner des rôles administrateur Discord, de distribuer des warns ni de blacklister des familles. La whitelist survit aux redémarrages de CrowBot.

## Warns

Les warns gardent un numéro historique : par exemple, `Sakura — Warn 1`. Si le warn 2 est retiré, le prochain warn est Warn 3 (pas Warn 2 de nouveau). Le nombre **d'avertissements actifs** se met à jour sur la fiche officielle. **Aucune blacklist automatique n'est appliquée au troisième warn** : la décision reste au Head of Families.

## Familles blacklistées

Le salon `#family-blacklist` héberge un ou plusieurs embeds mis à jour automatiquement (8 familles par page). Chaque entrée contient l'ID, le nom de la famille, l'ancien leader, le motif et la date. Une famille blacklistée **bloque une nouvelle candidature du même chef ou portant le même nom**. `/family-unblacklist` lève le blocage, mais **ne restaure pas les rôles ou salons précédemment supprimés**.

## Sécurité et limites

- `/family-remove` et `/family-blacklist` demandent `confirm:True` car la suppression des salons efface leur historique Discord. **Sauvegarde les données importantes avant de supprimer une famille.**
- CrowBot essaie de supprimer les seuls rôles et salons qu'il a lui-même enregistrés. En cas d'échec de nettoyage, la famille passe en état `REMOVING`, son accès de leader est bloqué, et la commande `/family-remove-retry` permet de reprendre. Ne supprime pas manuellement son entrée SQLite.
- Si les salons sont renommés ou supprimés, utilise `/family-channels` ou `/family-sync-boards` pour reconstituer les panneaux.
- Le bot doit avoir **Manage Roles** et **Manage Channels**, son rôle doit être au-dessus des rôles de famille, et il doit pouvoir envoyer et supprimer les messages dans les salons concernés. Il n'a pas besoin d'Administrator.
- L'envoi de DM à l'ancien chef est effectué quand possible. Il échoue silencieusement si ce dernier a fermé ses DM.
- Toutes les données (whitelist, avertissements, blacklist et IDs de messages) sont dans le même fichier SQLite. Pour conserver ces données sur Railway, utilise le **volume persistant** existant.
- **Non testé sur ton vrai serveur** : les tests locaux couvrent le stockage et la logique de migration, mais une vérification fonctionnelle des boutons et permissions Discord reste nécessaire avec ton bot.
