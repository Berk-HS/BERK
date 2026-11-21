# HighschoolRP CrowBot v2 — Official Families & Moderation

**This is an in-place upgrade for the original Families bot.** It retains the original application form, review buttons, family roles, private channels, and SQLite data. The Content Creator bot is separate and unchanged.

## ✨ New in v2

- **Official family announcements:** every approved family gets a branded, cyan-and-pink HS-logo embed in your selected `#official-families` channel. Existing approved families can be published retroactively with `/family-channels` or `/family-sync-boards`. Active warning counts update on the family card.
- **Family removal whitelist:** members request special permission via `/family-whitelist-request`. Heads of Families approve or decline in the private review channel using persistent buttons. Approved whitelisted users can use `/family-remove` only; they do not receive Discord Administrator permissions.
- **Numbered warning system:** `/family-warn`, `/family-warns`, `/family-unwarn` create numbered, auditable warnings and update public family cards. Warnings **do not trigger automatic blacklisting**.
- **Public blacklist:** `/family-blacklist` removes the family's private roles/channels and official announcement, then publishes it in the selected `#family-blacklist` register. Supports multiple pages and public reason/date. The same family name or leader cannot reapply until `/family-unblacklist` is used.
- **Safe moderation:** destructive commands require `confirm:True`. Partial/failed removals are recoverable using `/family-remove-retry`. Data is migrated in-place on startup; no reset is required.

> **Existing users:** Read [`UPGRADE_GUIDE_FR.md`](UPGRADE_GUIDE_FR.md) before replacing the old bot. Stop your bot first and back up `.env` and your existing SQLite file. Keep the same `DATABASE_PATH` and Railway Volume if you are hosting it.

### Setup for your existing HighschoolRP server

1. Create `#official-families` and `#family-blacklist` as **public read-only channels** (members may read but cannot type). CrowBot must be allowed to send messages, embed links, attach files and read history in both channels.
2. Start the updated CrowBot with your **existing** `.env` and `data/families.sqlite3`.
3. Run **`/family-channels official_families:#official-families family_blacklist:#family-blacklist`** as a server manager. This also publishes **already-approved** families. You do not need to repeat `/family-setup` if your old configuration is valid.
4. Use `/family-sync-boards` if you need to repair the embeds later.

### New slash commands

| Command | Access | Description |
| --- | --- | --- |
| `/family-channels` | Manage Server / administrator | Configure official announcement and blacklist channels |
| `/family-sync-boards` | Head of Families / server manager | Reconcile the public official-family cards and blacklist board |
| `/family-whitelist-request` | Any member | Apply for family removal whitelist |
| Private Approve / Decline buttons | Head of Families / server manager | Approve or decline a whitelist request posted in the existing review channel |
| `/family-whitelist-list` | Head / manager | List pending and approved whitelist users |
| `/family-whitelist-revoke member:@User` | Head / manager | Revoke a whitelisted user's access |
| `/family-whitelist-repost request_id:1` | Head / manager | Repost a missing pending whitelist review card |
| `/family-remove application_id:1 reason:... confirm:True` | Whitelist, Head or manager | Permanently remove official roles, private family channels and official announcement |
| `/family-remove-retry application_id:1` | Head / manager, or whitelist for plain removals | Resume interrupted cleanup |
| `/family-warn application_id:1 reason:...` | Head / manager | Issue numbered public family warning |
| `/family-warns application_id:1` | Everyone | Inspect warning history |
| `/family-unwarn application_id:1 warn_number:1 reason:...` | Head / manager | Revoke an active warning, retaining history |
| `/family-blacklist application_id:1 reason:... confirm:True` | Head / manager | Blacklist a currently approved family and remove its roles/channels |
| `/family-unblacklist application_id:1 reason:...` | Head / manager | Lift a blacklist; does not restore deleted roles/channels |
| `/family-blacklist-list` | Everyone | Summarize blacklisted families |

**Find family application IDs** in the footer of the official-family embeds or `/family-directory`. Never share your Discord token. Blacklisted families are blocked from submitting under the same leader or family name until the blacklist is lifted. Removing a blacklist allows the former leader to submit a **new application**, but does not recreate any deleted channels.

---

A complete, English-language Discord bot for the **HighschoolRP** official family system.

**Status:** Source code and deployment files are provided. The bot has **not** been connected to your Discord account or deployed. A Discord bot token and a hosting account are required for it to go online.

## Features

- Branded application panel with your original HS / cherry blossom logo and a button.
- Application modal requesting **family name**, **current member count**, **server/community** (for example, `North America` or `Spanish`), **13+ / 18+ group**, and **HEX role color**.
- Private application queue for the **Head of Families** with **Approve Family** and **Decline Family** buttons.
- Applications remain pending until an authorized reviewer decides.
- On approval, automatically creates **both** colored and hoisted roles:
  - `Leader [Family Name]`
  - `Member of [Family Name]`
- Gives the family founder the leader role; the leader can then add members via `/family-add`.
- Creates **one private family category** containing `#announcements`, `#chat`, `#media` and `Family Voice`.
- The announcements channel is **read-only for members** but writable by leaders / the Head of Families.
- Family leaders and members are separated into Discord member-list groups when no higher hoisted role takes priority.
- Status tracking, a directory of official families, and review recovery commands.
- SQLite stores applications and created roles/channels; persistent Discord buttons survive bot restarts.
- Dockerfile + Railway configuration for an always-on hosted service.

**Important:** The family age group is a descriptive application field. The bot does **not** verify a user's age. The listed member count is informative, not an automatic membership limit.

## 1. Create your Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and name it `HighschoolRP CrowBot` (or `CrowBot`).
3. Under **Bot**, copy or reset the **bot token**. Keep it secret. Never post it to Discord, GitHub, a support ticket or a screenshot.
4. Under **Bot**, upload the included `assets/bot-avatar.png` as the bot's avatar. The full original logo is automatically used on the application's Discord embeds.
5. Under **Installation** / **OAuth2**, create a **Guild Install** link with scopes **`bot`** and **`applications.commands`**.
6. Grant these bot permissions:
   - Manage Roles
   - Manage Channels
   - View Channels
   - Send Messages
   - Read Message History
   - Embed Links
   - Attach Files
   - Connect (for voice access)
7. Invite the bot to your **HighschoolRP Discord server** using the generated link.
8. In **Server Settings → Roles**, drag the bot's role **above every role it will create or assign**. The Head of Families role does not need to be below the bot unless the bot must manage that role (it does not).

You do **not** need to enable the privileged *Message Content Intent* or *Server Members Intent* for this version. This bot uses slash commands and Discord's REST API.

## 2. Run it on Windows (for testing)

1. Extract the ZIP file into a folder such as `Desktop\HighschoolRP-CrowBot`.
2. Install [Python 3.12](https://www.python.org/downloads/) and select **Add python.exe to PATH** if the installer offers it.
3. Double-click **`INSTALL_WINDOWS.bat`**. This installs the two Python packages and opens a `.env` configuration file.
4. Edit the `.env` file:

```env
DISCORD_TOKEN=YOUR_REAL_BOT_TOKEN
DISCORD_GUILD_ID=YOUR_DISCORD_SERVER_ID
DATABASE_PATH=data/families.sqlite3
```

**How to find your server ID:** Discord → Settings → Advanced → Developer Mode → right-click the HighschoolRP server icon → **Copy Server ID**.

5. Save the file. Double-click **`START_WINDOWS.bat`** and leave the window open.
6. In Discord, test **`/family-ping`**. If the bot answers, it is connected.

Alternative using PowerShell from the extracted folder:

```powershell
py -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
py bot.py
```

Do not run `Copy-Item` again if you have already created and edited `.env`, or you may overwrite your setup.

## 3. Configure the family system in Discord

Create two text channels in your server:

- **`#family-applications`**: visible to the members who will apply.
- **`#family-reviews`**: private, visible to the **Head of Families** and appropriate server managers.

Create a **Head of Families** role and assign it to the people allowed to review applications.

As a server administrator or someone with **Manage Server**, enter:

```text
/family-setup applications:#family-applications reviews:#family-reviews head_of_families:@Head of Families
```

Select your actual channels and role from Discord's autocomplete. The bot will post the public family application panel immediately.

**What an application looks like:**

```text
Family Name: Sakura
Current number of members: 12
Server / community: North America
Age group: 13+
Role color: #00FFFF
```

The Head of Families reviews the request in `#family-reviews`. **Approving** creates the roles and the four private channels, then gives `Leader Sakura` to the applicant. **Declining** does not create anything; the applicant can apply again later.

A family category is a Discord channel container. Discord does **not** allow channels to be placed *inside another text channel*. Applications appear in your selected application channel; approved families receive their own private category.

## 4. Discord slash commands

| Command | Who can use it | What it does |
| --- | --- | --- |
| `/family-setup` | Server manager | Configure the panel, review channel and Head of Families role |
| `/family-panel` | Server manager | Post another application panel |
| `/family-pending` | Head / manager | List pending application IDs |
| `/family-review application_id:123` | Head / manager | Repost a missing review card |
| `/family-recover application_id:123` | Head / manager | Clean up resources left by an interrupted approval |
| `/family-approve application_id:123` | Head / manager | Manually approve a request |
| `/family-decline application_id:123 reason:...` | Head / manager | Manually decline a request |
| `/family-status` | Family applicant | Check their latest application status |
| `/family-directory` | Everyone | List approved families |
| `/family-add member:@Player` | Approved family leader | Add a family member and grant the member role |
| `/family-kick member:@Player` | Approved family leader | Remove a family member role |
| `/family-ping` | Everyone | Confirm the bot is running |

The bot prevents a user from having multiple active family applications. Family leaders cannot use `/family-add` to place a member into a second official family. The founder gets the leader role only; the member role is used for other family members.

## 5. Host it 24/7 using Railway

A bot cannot stay online after you shut down your PC unless it runs on an external server. **Railway** is one hosting option. It can run the bot as a background service, with restart and persistent storage features. Availability and charges depend on your Railway plan; no platform guarantees uninterrupted uptime. The included `railway.json` requests Railway's **Always** restart policy, which requires a **paid Railway plan**. If using a Free or Trial plan for testing, change `"restartPolicyType": "ALWAYS"` to `"restartPolicyType": "ON_FAILURE"` and add `"restartPolicyMaxRetries": 10` in `railway.json`.

1. Create a **private GitHub repository** containing the extracted project files. Upload `bot.py`, `requirements.txt`, `Dockerfile`, `railway.json`, `assets/` and the other included files. **Do not upload `.env`** (it is already excluded by `.gitignore` for Git users).
2. Go to [railway.com](https://railway.com/) → **New Project → Deploy from GitHub Repo** → select your private repository.
3. In the Railway service, open **Variables**, add:

```env
DISCORD_TOKEN=YOUR_REAL_BOT_TOKEN
DISCORD_GUILD_ID=YOUR_DISCORD_SERVER_ID
DATABASE_PATH=/data/families.sqlite3
```

4. Attach a **Volume** to your Railway service, with **mount path exactly `/data`**. This ensures applications and family information survive redeploys.
5. Ensure the service has **1 replica** and is configured as a continuously running service, not a scheduled job or sleeping web service. The included Dockerfile and `railway.json` already launch `python bot.py`. Use an eligible paid plan for its **Always** restart policy.
6. Deploy the staged changes and open **Deploy Logs**. Look for `CrowBot ready as ...`.
7. Run `/family-ping` in your Discord server to verify the live bot. You do not need a public domain, webhook address or Cloudflare tunnel.

**Storage warning:** without the persistent Volume and matching `DATABASE_PATH`, your SQLite database may disappear during a redeploy. Existing Discord roles and channels will remain but the bot may forget their ownership relationships. Back up your volume regularly.

Railway documentation: [Services](https://docs.railway.com/services), [Variables](https://docs.railway.com/variables), [Volumes](https://docs.railway.com/volumes), [Restart policy](https://docs.railway.com/deployments/restart-policy).

## 6. Troubleshooting

**The bot is offline.** Check that `DISCORD_TOKEN` is correct, the PowerShell window is still running (local only), or Railway Deploy Logs show a successful connection.

**Slash commands do not show.** Ensure both OAuth2 scopes are set correctly; verify `DISCORD_GUILD_ID`; restart the bot after adding it to the server. Guild-scoped commands are registered on bot startup.

**Approval fails.** Check **Manage Roles** and **Manage Channels** and move the bot role higher in the role list. Make sure the founder is still in the Discord server and the Head of Families role still exists. The bot tries to delete partially created resources when an approval fails.

**The bot can't send a review card.** Check channel permissions in `#family-reviews`. The application is still saved. A Head of Families can use `/family-pending` and `/family-review application_id:<ID>`.

**The leader or member isn't grouped separately in the sidebar.** Both family roles have **Display role members separately** enabled. Discord determines sidebar grouping using the member's highest eligible hoisted role; a higher staff / VIP role can take precedence. Server owners can adjust role order manually.

**Family members don't see their channels.** Check private category overrides and verify users were given the correct member role with `/family-add`. Administrators can always see private channels because of Discord's administrator permission.

**After a severe shutdown mid-approval.** The bot attempts recovery on startup by deleting the recorded partial resources and restoring the pending request. If role/channel deletion fails due to permissions, a Head can fix permissions and run `/family-recover application_id:<ID>`. Unrecorded orphaned resources from a hard crash may still need manual cleanup. Avoid running multiple bot replicas against the same SQLite file.

## Files

- `bot.py` — main Discord bot application
- `assets/highschoolrp-logo.png` — original uploaded logo used in embeds
- `assets/bot-avatar.png` — 512×512 avatar upload for Developer Portal
- `.env.example` — environment configuration template
- `requirements.txt` — Python dependencies
- `Dockerfile`, `railway.json`, `Procfile` — deployment entry points
- `INSTALL_WINDOWS.bat`, `START_WINDOWS.bat` — easier Windows setup
- `data/` — local SQLite database directory (created when the bot starts)

**Privacy and safety:** Keep the review channel private and your Discord token secret. Role assignment is limited to the bot's configured official families; family members cannot grant roles from other families. Protect backups of `families.sqlite3` because they contain Discord user IDs and the submitted family information.
