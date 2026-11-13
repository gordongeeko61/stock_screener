# Nifty Momentum Screener

A cloud-run daily screener for Nifty sectoral indices.

## Data policy
- Primary: Nifty Indices official Historical Data page and its underlying historical-data service.
- Independent cross-check: NSE official daily all-indices archive (`ind_close_all_DDMMYYYY.csv`).
- ATH is calculated from the full returned historical close series. Never substitute 52-week high for ATH.
- The Nifty Indices historical-data POST endpoint is not a documented stable public API. It may change or apply bot protection. The workflow intentionally fails rather than silently publish guessed data.
- Before using the output for investment decisions, validate the source access and index universe coverage. For commercial/production use, obtain an authorized exchange data licence/feed.

## Momentum model
Cross-sectional percentile composite across configured sectors:
- 1-month return: 10%
- 3-month return: 20%
- 6-month return / annualized 1-year volatility: 25%
- 12-month return / annualized 1-year volatility: 25%
- Trend confirmation (above 50 DMA, above 200 DMA, 50 DMA rising): 15%
- RSI(14) health score: 5%

The score is a relative ranking within the configured universe, not an absolute probability or a trading recommendation.

## Deploy
1. Create a GitHub repository and upload this project.
2. In repository Settings → Pages, set Build and deployment to GitHub Actions.
3. Run the `Daily Nifty Momentum Screener` workflow once manually.
4. The workflow runs weekdays at 18:45 IST and publishes `docs/` as a GitHub Pages site.
5. Add the resulting URL to iPhone Home Screen using Safari → Share → Add to Home Screen.

## Privacy
GitHub Pages sites are public. Do not publish private data or credentials. This project publishes index data only. Email credentials, if added later, must be GitHub Actions secrets and never committed to the repository.

## Reliability gates to add before production
- Confirm each configured index exists and that history covers its true inception date.
- Compare last close against NSE archive for the same date and matching index name.
- Reject stale or partial index sets from the final shortlist.
- Persist a versioned daily history file and add a data-source health status.
- Consider an authorized data vendor if NSE blocks automated retrieval or if this is used for production/commercial decisions.


## Optional daily email
Add these repository Actions secrets:
- `SMTP_HOST` (Gmail: `smtp.gmail.com`)
- `SMTP_PORT` (`587`)
- `SMTP_USER` (sender email)
- `SMTP_PASSWORD` (Gmail app password; do not use your normal account password)
- `REPORT_TO` (recipient email)

If secrets are not configured, the workflow still publishes the dashboard and skips email.
