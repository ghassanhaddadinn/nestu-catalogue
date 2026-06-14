# NESTU® Product Catalogue — Auto-Generation System

Live HTML flipbook catalogues for Jordan, UAE, and KSA.
Auto-refreshes every 30 minutes from live Odoo stock data.

## Live URLs (after GitHub Pages setup)
- **Jordan:** `https://nestu-ltd.github.io/nestu-catalogue/jordan.html`
- **UAE:**    `https://nestu-ltd.github.io/nestu-catalogue/uae.html`
- **KSA:**    `https://nestu-ltd.github.io/nestu-catalogue/ksa.html`

---

## One-Time Setup

### 1. Clone and place assets

```bash
git clone https://github.com/Nestu-Ltd/nestu-catalogue.git
cd nestu-catalogue
```

Copy Neulis Alt fonts into `./fonts/`:
```
fonts/
  NeulisAlt-Black.otf
  NeulisAlt-Medium.otf
  NeulisAlt-Regular.otf
```

Process the NESTU logo (run once):
```bash
pip install Pillow
python setup_assets.py --logo "path/to/nestu_logo.png"
```

This creates `assets/logo_white.png` and `assets/logo_blue.png`.

### 2. Add GitHub Secrets

Go to: GitHub repo → Settings → Secrets and variables → Actions → New repository secret

| Secret | Value |
|---|---|
| `ODOO_URL` | `https://nestu.odoo.com` |
| `ODOO_DB` | `odooerp-ae-nestu-health-main-12720997` |
| `ODOO_USERNAME` | `ghassan@nestu.health` |
| `ODOO_API_KEY` | *(your Odoo API key)* |

### 3. Enable GitHub Pages

GitHub repo → Settings → Pages → Source: Deploy from a branch → Branch: `main` → Folder: `/docs`

### 4. Commit fonts and assets

```bash
git add fonts/ assets/ config/
git commit -m "Add fonts, logo assets, and dear doctor letter"
git push
```

### 5. Trigger first run

GitHub → Actions → "Refresh NESTU Catalogues" → Run workflow

---

## Local Testing

```bash
# Windows PowerShell
$env:ODOO_URL      = "https://nestu.odoo.com"
$env:ODOO_DB       = "odooerp-ae-nestu-health-main-12720997"
$env:ODOO_USERNAME = "ghassan@nestu.health"
$env:ODOO_API_KEY  = "your_api_key"

python generate.py           # All three countries
python generate.py jordan    # Jordan only
python generate.py --check   # Check for missing images (no HTML output)
```

---

## How the Automation Works

Every 30 minutes, GitHub Actions runs `generate.py` which:

1. Connects to Odoo via XML-RPC API
2. Queries `stock.quant` per company (Jordan=2, UAE=3, KSA=4) for `qty > 0` in internal locations
3. Fetches product templates, images, tags (brands), and categories
4. Groups products by brand tag (alphabetical by brand, then by product name)
5. Downloads and resizes product images (cached in `cache/images/` — not committed to repo)
6. Generates a self-contained HTML flipbook per country
7. Commits the updated `docs/*.html` files to GitHub Pages

A product **appears** in the catalogue within 30 minutes of its first GRN being validated in Odoo.
A product **disappears** when its stock drops to zero.

---

## Updating the Dear Doctor Letter

Edit `config/dear_doctor.txt` — the next automated run picks it up automatically.

## Image Cache

Product images are cached in `cache/images/` to avoid fetching on every run.
To force refresh all images (e.g. after updating product photos in Odoo):
```bash
rm -rf cache/images/
python generate.py
```

The `cache/` directory is in `.gitignore` and is not committed to the repo.
GitHub Actions rebuilds the cache from scratch on each run (this is fine — images are small).

---

## File Structure

```
nestu-catalogue/
├── generate.py            Main catalogue generator
├── setup_assets.py        One-time logo processor
├── .github/
│   └── workflows/
│       └── refresh.yml    GitHub Actions (every 30 min)
├── fonts/                 Neulis Alt OTF files (commit to repo)
│   ├── NeulisAlt-Black.otf
│   ├── NeulisAlt-Medium.otf
│   └── NeulisAlt-Regular.otf
├── assets/                Processed logos (commit to repo)
│   ├── logo_white.png
│   └── logo_blue.png
├── config/
│   └── dear_doctor.txt    Letter text (edit freely)
├── cache/
│   └── images/            Product image cache (gitignored)
└── docs/                  GitHub Pages output
    ├── index.html          Country selector landing page
    ├── jordan.html         Auto-generated
    ├── uae.html            Auto-generated
    └── ksa.html            Auto-generated
```
