# Letterboxd Custom Report

This repository publishes a shareable Letterboxd analysis site to GitHub Pages and now supports automatic refresh from the public Letterboxd profile for `goorison`.

## What updates automatically

- Public diary entries
- Public reviews and review text
- Public tags attached to diary/review entries
- Public watchlist
- Public custom lists and list contents
- The generated website at `index.html`

## How it works

1. GitHub Actions fetches the public Letterboxd profile pages and RSS feed.
2. The sync script rebuilds a local export-like folder with `ratings.csv`, `diary.csv`, `reviews.csv`, `watchlist.csv`, `profile.csv`, and `lists/*.csv`.
3. The existing custom report generator rebuilds the site.
4. If full-page fetching is challenged, the workflow keeps the last complete analysis and still refreshes `recent-activity.json` from the public RSS feed.
5. The page shows recent public activity separately and identifies the date of the last complete analysis. Changed published files are committed to `main`.

## Schedule

- Every 6 hours: incremental refresh of the newest public activity
- Every Sunday: full refresh of cached diary/review detail pages
- Any time: manual run from the `Actions` tab with `workflow_dispatch`

## Important limitation

This automation is based on public pages and RSS, not on the private Letterboxd export bundle or private API access. That means it can stay hands-off, but it may miss data that only exists in account exports or private content.

Letterboxd sometimes serves a Cloudflare challenge to automated full-page requests. During those periods the RSS panel can stay current, but historical analysis totals, lists, tags, and recommendations remain at the last complete rebuild. A Letterboxd export is needed to reconcile a fully current snapshot if public-page access remains blocked.

## Local run

From the repository root:

```bash
./scripts/run_public_sync.sh
```

If you ever want to point this at a different public Letterboxd account, change the default username in:

- `.github/workflows/sync-letterboxd-public.yml`
- `scripts/run_public_sync.sh`
