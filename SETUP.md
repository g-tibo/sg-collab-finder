# Setup guide (Windows)

This walks through installing what you need and getting the site running locally,
then deploying to Vercel.

## 1. Install Node.js

The web app needs Node 20 or newer. Install via winget in PowerShell:

```powershell
winget install OpenJS.NodeJS.LTS
```

Close and reopen your terminal, then confirm:

```powershell
node --version   # should print v20.x or v22.x
npm --version
```

(Alternative: download the LTS installer from https://nodejs.org.)

## 2. Run the web app locally

Python is already installed (you have 3.12) so the scraper already ran and a
seed `web/public/faculty.json` is committed.

```powershell
cd sg-collab-finder\web
npm install
npm run dev
```

Open http://localhost:3000. Browse should work without any key. On the
**AI Match** page, paste your Anthropic API key in the input (stored only in
your browser's localStorage) or skip that step if you set `ANTHROPIC_API_KEY`
in `.env.local`.

## 3. Deploy to Vercel

1. Create a GitHub repo and push the whole `sg-collab-finder/` folder.
2. On https://vercel.com, **Import Project** → pick the repo.
3. Set **Root Directory** to `web`.
4. (Optional) Add an environment variable `ANTHROPIC_API_KEY` so visitors
   don't have to bring their own key.
5. Deploy. Vercel auto-detects Next.js.

## 4. Refresh the data

Whenever you want an updated snapshot:

```powershell
cd sg-collab-finder\scraper
pip install -r requirements.txt
python -m scrapers.ntu_sbs
python -m scrapers.astar_imcb
python -m scrapers.nus_dbs          # lite mode — names + titles + URLs
python merge.py                     # produces web\public\faculty.json
```

Commit and redeploy.

### Full NUS scrape (optional)

NUS sites use Incapsula bot protection, so the lightweight `requests`-based
scraper can't see real content. Use Playwright with a real browser:

```powershell
cd sg-collab-finder\scraper
pip install playwright
playwright install chromium
python -m scrapers.nus_dbs --full
python merge.py
```

This takes a few minutes and produces research-interest text for each NUS DBS
profile. You may need to run it from a residential connection (not a cloud VM)
for Incapsula to clear you.

## 5. Adding another institution

Each institution is one Python module in `scraper/scrapers/`. Copy
`ntu_sbs.py` as a starting point, update the index URL and the extractor, then
add the output file to `SOURCES` in `scraper/merge.py`.

Short wishlist (see `README.md` for the long list):
- NUS Yong Loo Lin School of Medicine
- NTU Lee Kong Chian School of Medicine
- NTU CCEB (Chemistry, Chemical Engineering & Biotechnology)
- A*STAR: GIS, BII, SIgN, IMB, BTI, IHPC, I2R (same Sitefinity CMS as IMCB;
  the `astar_imcb.py` scraper should mostly transplant by changing the URL)
- Duke-NUS Medical School
- Temasek Life Sciences Laboratory (TLL)
- National Neuroscience Institute
- National Cancer Centre Singapore
- Singapore Eye Research Institute / SNEC
