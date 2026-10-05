# How to run MDS-Corp

This repo is local tooling for [mdsindustrialcorp.com](https://mdsindustrialcorp.com): WordPress connection, Google Search Console indexing checks, Google Business Profile posting, and a local dashboard.

Secrets are **not** in Git. Each person creates them on their own computer.

## 1. What you need

- Git
- Python 3 (`python3` in Terminal)
- Google Chrome (for Search Console login)
- macOS is what this project was set up on

No `npm` or `pip` install is required.

## 2. Clone

```bash
git clone https://github.com/Pramod-Gharu/MDS-Corp.git
cd MDS-Corp
```

## 3. Google Search Console (indexing)

Required if you will check or refresh page indexing.

### Access

- A Google account that can open Search Console for `sc-domain:mdsindustrialcorp.com`
- While **MDS Corp App** is in Testing, that Google email must be listed as an OAuth **test user**

### Credentials (ask a teammate; do not put these in Git)

- OAuth **Client ID**
- OAuth **Client secret**

These are shared for the team. Each person still logs in themselves.

### Save credentials locally

```bash
python3 scripts/gsc_save_oauth.py
```

Paste:

- Client ID
- Client secret
- Application type: `desktop` (press Enter)

That writes `.mds/gsc-oauth.json` (gitignored).

Or create `.mds/gsc-oauth.json` yourself:

```json
{
  "site_url": "sc-domain:mdsindustrialcorp.com",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "application_type": "desktop"
}
```

### One-time Google login

```bash
python3 scripts/gsc_connect.py login
```

Chrome opens. Choose the Search Console account, then click **Allow**.

The browser tab may say “Google login complete” before the terminal finishes. Success is the terminal line:

```text
login	ok
```

Check:

```bash
python3 scripts/gsc_connect.py status
```

You want:

```text
auth	ok
property	ok	sc-domain:mdsindustrialcorp.com
```

Do **not** copy another person’s `refresh_token`. Run `login` on your machine.

## 4. Google Business Profile (posts)

Required after Google approves Basic API Access (quota **300 QPM**).

Also enable these APIs on the same Cloud project:

- My Business Account Management API
- My Business Business Information API
- Google My Business API

Save the OAuth client locally (reuses Search Console credentials if those already exist):

```bash
python3 scripts/gbp_save_oauth.py
python3 scripts/gbp_connect.py login
```

Chrome opens. Choose the Google account that **manages** the MDS Industrial listing, then click **Allow**.

Check:

```bash
python3 scripts/gbp_connect.py status
```

You want `auth ok` and one location.

Publish a post from a blog article (title, featured image, Learn more, UTM link):

```bash
python3 scripts/gbp_connect.py from-blog "https://mdsindustrialcorp.com/pallet-shelving-warehouse-costs/"
```

That always adds `utm_source=GBP_post` and `utm_medium=page_share` to the Learn more link.

In Cursor chat you can also:

- Paste the live blog URL, or
- Run `/gbp-post https://mdsindustrialcorp.com/YOUR-NEW-ARTICLE/`

The `gbp-blog-post` skill then publishes it in the same format.

Keyword posts come from the Google Sheet (saved only in local `.mds/gbp-sheet.json`):

```bash
python3 scripts/gbp_connect.py keywords
python3 scripts/gbp_connect.py from-keyword "Pallet Racking"
```

Or in chat: `/gbp-keyword Pallet Racking`

That uses the sheet Description, Drive image, Learn more, and the same UTM parameters. `/gbp-post` is unchanged.

## 5. WordPress (optional)

Required only if you will call the live WordPress API.

Create `.mds/wp.json` (gitignored):

```json
{
  "site": "https://mdsindustrialcorp.com",
  "user": "YOUR_WP_USERNAME",
  "secret": "YOUR_APPLICATION_PASSWORD"
}
```

Use your own application password. Do not commit this file.

Check:

```bash
python3 scripts/wp_connect.py status
```

You want `public	ok` and, if credentials are set, `auth	ok`.

## 6. Indexing dashboard

```bash
python3 scripts/gsc_dashboard.py open
```

Opens:

- http://127.0.0.1:8765/
- http://127.0.0.1:8765/indexing.html

The HTML in the repo is a saved snapshot. To pull **live** status from Google (after step 3 works):

```bash
python3 scripts/gsc_dashboard.py refresh
python3 scripts/gsc_dashboard.py open
```

`refresh` inspects every URL in:

- https://mdsindustrialcorp.com/post-sitemap.xml (Blog)
- https://mdsindustrialcorp.com/page-sitemap.xml (Homepage and service pages)
- https://mdsindustrialcorp.com/service-areas-sitemap.xml (Service areas)

## 7. What success looks like

| Command | Expected |
|---|---|
| `python3 scripts/gsc_connect.py status` | `auth ok` and property ok |
| `python3 scripts/gsc_dashboard.py open` | Dashboard at http://127.0.0.1:8765/ |
| `python3 scripts/wp_connect.py status` | `auth ok` if you set WordPress |
| `python3 scripts/gbp_connect.py status` | `auth ok` and one location |

## 8. Agent-based work

The main folder is the **orchestrator**. Each new job is a **separate agent**.

```bash
./scripts/mds-task add homepage-hero --title "Homepage hero" --path "wp-content/themes/mds/front-page.php"
./scripts/mds-task list
./scripts/mds-task remove homepage-hero
```

`remove` deletes only that agent’s worktree and branch. Other agents keep their files.

Details: [docs/AGENTS.md](AGENTS.md).

## 9. Do not commit

These stay only on your computer (already in `.gitignore`):

- `.mds/wp.json`
- `.mds/gsc-oauth.json`
- `.mds/gsc-index.json`
- `.mds/gbp-oauth.json`
- `.mds/gbp-sheet.json`

Never put Client secrets, application passwords, or tokens in GitHub, the README, or chat.

## 10. Git after you change code

Saving files in Cursor does not update GitHub. After a feature:

```bash
git add -A
git status
```

Confirm `.mds/` is **not** listed, then commit and push. Or ask in Cursor: **commit and push**.
