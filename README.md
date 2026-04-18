# SG Collab Finder

A directory of faculty at Singapore research institutions, with an optional AI
matching feature powered by Claude. Inspired by
[plen-collab-finder](https://plen-collab-finder.vercel.app/), adapted for the
Singapore research ecosystem.

v1 coverage: **NTU School of Biological Sciences**, **A*STAR Institute of
Molecular and Cell Biology (IMCB)**, and a NUS Department of Biological Sciences
seed. Designed to be extended to NUS Medicine, Duke-NUS, TLL, NNI, NCCS, SNEC,
the rest of A*STAR, and other institutions in the
[Wikipedia category](https://en.wikipedia.org/wiki/Category:Research_institutes_in_Singapore).

## Repository layout

```
sg-collab-finder/
├── web/               Next.js 15 + TypeScript + Tailwind app (deploy to Vercel)
│   ├── app/           Pages: Browse (/), AI Match (/match), About (/about)
│   ├── app/api/match  Claude ranking endpoint
│   ├── public/        Static assets; faculty.json lives here
│   └── package.json
└── scraper/           Python scrapers that produce web/public/faculty.json
    ├── scrapers/      One extractor per institution
    ├── merge.py       Combines per-institution JSON into one file
    └── requirements.txt
```

## Quickstart — run the web app

Requires Node 20+.

```bash
cd web
npm install
npm run dev           # open http://localhost:3000
```

A seed `web/public/faculty.json` is committed so the UI works out of the box.
Leave the Anthropic key empty and the AI Match page will prompt the visitor to
paste their own.

## Deploy to Vercel

1. Push this repo to GitHub.
2. On vercel.com, **Import Project** → pick the repo → set **Root Directory** to
   `web`.
3. (Optional) Add `ANTHROPIC_API_KEY` as an environment variable so visitors
   don't need their own key. Without it, the AI Match page falls back to asking
   visitors to paste a key.
4. Deploy. No database or build-time secrets required.

## Refresh the faculty data

```bash
cd scraper
pip install -r requirements.txt
python -m scrapers.ntu_sbs       # -> scraper/out/ntu_sbs.json
python -m scrapers.astar_imcb    # -> scraper/out/astar_imcb.json
# NUS scrapers require Playwright; see scrapers/nus_dbs.py header
python merge.py                  # -> web/public/faculty.json
```

Then commit and redeploy. The data is intentionally a static snapshot: no
database, no auth, no tracking — matching the design philosophy of the original
`plen-collab-finder`.

## Extending to more institutions

Each institution is one Python file in `scraper/scrapers/` that exports:

```python
def scrape() -> list[dict]: ...
```

returning records shaped like `scraper/schema.py`. Add a new file, add it to the
list in `merge.py`, rerun. See `ntu_sbs.py` as the reference implementation.

Institutions on the v1 wishlist (in rough priority order):

- NUS Yong Loo Lin School of Medicine
- NUS Faculty of Science (Chemistry, Pharmacy, Biochemistry, Physiology, etc.)
- NTU Lee Kong Chian School of Medicine
- NTU School of Chemistry, Chemical Engineering & Biotechnology (CCEB)
- A*STAR: GIS, BII, SIgN, IMB, BTI, SIMTech, IHPC, I2R, etc. (~20 RIs total)
- Duke-NUS Medical School
- Temasek Life Sciences Laboratory (TLL)
- National Neuroscience Institute (NNI)
- National Cancer Centre Singapore (NCCS)
- Singapore Eye Research Institute / SNEC
- Lee Kong Chian School of Medicine
- SMART (MIT research enterprise in Singapore)
- Singapore Immunology Network

## Data and ethics

All profile data is scraped from public institutional web pages. The About page
exposes a contact email (yours) so researchers can request correction or
removal. No user accounts, analytics, or tracking; AI match queries are not
retained by this site.

## License

MIT.
