# Selfhost SEC EDGAR Data API

REST API for fetching SEC EDGAR Data with Docker and Docker compose.


## Quick Start

### Option A — Docker (recommended)

```bash
# Clone / download this project
git clone https://github.com/yourname/sec-edgar-api
cd sec-edgar-api

# Build and run
docker compose up -d

# Verify
curl http://localhost:8000/v1/company/MSFT
```

### Option B — Local Python

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open **http://localhost:8000/docs** for the interactive Swagger UI.



## Endpoints

### `GET /v1/company/{ticker}`
Returns company metadata: CIK, SIC code, state of incorporation, fiscal year end, exchanges.

```
GET /v1/company/AAPL
```
```json
{
  "ticker": "AAPL",
  "cik": "0000320193",
  "name": "Apple Inc.",
  "sic": "3674",
  "sic_description": "Semiconductors",
  "state_of_incorporation": "CA",
  "fiscal_year_end": "0930",
  "exchanges": ["Nasdaq"],
  "tickers": ["AAPL"],
  "ein": "94-2404110",
  "category": "Large accelerated filer"
}
```

---

### `GET /v1/company?q={query}`
Search companies by ticker or name fragment.

```
GET /v1/company?q=apple&limit=5
```
```json
[
  { "ticker": "AAPL", "cik": "0000320193", "name": "Apple Inc." },
  { "ticker": "APLE", "cik": "0001418121", "name": "Apple Hospitality REIT, Inc." }
]
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `q` | string | required | Ticker or name fragment |
| `limit` | int | 10 | Max results (1–50) |

---

### `GET /v1/filings/{ticker}`
SEC filing history with direct links to SEC.gov.

```
GET /v1/filings/AAPL?form=10-K&limit=5
```
```json
{
  "ticker": "AAPL",
  "cik": "0000320193",
  "name": "Apple Inc.",
  "total": 5,
  "filings": [
    {
      "accession_number": "0000320193-23-000077",
      "filing_date": "2023-11-03",
      "report_date": "2023-09-30",
      "form": "10-K",
      "primary_document": "aapl-20230930.htm",
      "filing_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019323000077/",
      "document_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019323000077/aapl-20230930.htm",
      "is_inline_xbrl": true
    }
  ]
}
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `form` | string | (all) | Filter by form type: `10-K`, `10-Q`, `8-K`, etc. |
| `limit` | int | 20 | Max results (1–200) |

---

### `GET /v1/filings/{ticker}/{accession_number}`
Fetch full text content of a specific SEC filing document.

This endpoint allows custom models to retrieve detailed content from a filing by referencing the accession number obtained from the `/v1/filings/{ticker}` lookup endpoint.

**Workflow:**
1. Call `GET /v1/filings/AAPL` to get available filings and accession numbers
2. Select a filing and note its `accession_number`
3. Call `GET /v1/filings/AAPL/0000320193-23-000077` to fetch full document content

```
GET /v1/filings/AAPL/0000320193-23-000077
```
```json
{
  "ticker": "AAPL",
  "cik": "0000320193",
  "name": "Apple Inc.",
  "filing": {
    "accession_number": "0000320193-23-000077",
    "filing_date": "2023-11-03",
    "form": "10-K",
    "primary_document": "aapl-20230930.htm",
    "document_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019323000077/aapl-20230930.htm",
    "content": "<html><body>... full filing document HTML/text content ...</body></html>",
    "content_type": "text/html",
    "content_length": 1234567
  }
}
```

**Parameters**

| Name | Type | Description |
|---|---|---|
| `ticker` | string | Company ticker symbol (e.g., `AAPL`) |
| `accession_number` | string | Filing accession number (e.g., `0000320193-23-000077`) or `0000320193-24-000006` |

**Response Fields**

| Field | Type | Description |
|---|---|---|
| `ticker` | string | Company ticker |
| `cik` | string | 10-digit Central Index Key |
| `name` | string | Company legal name |
| `filing.accession_number` | string | Filing accession number |
| `filing.filing_date` | string | Date filing was submitted (YYYY-MM-DD) |
| `filing.form` | string | Form type (10-K, 10-Q, 8-K, etc.) |
| `filing.primary_document` | string | Primary document filename |
| `filing.document_url` | string | Direct URL to the document on SEC.gov |
| `filing.content` | string | Full text content of the filing document |
| `filing.content_type` | string | MIME type of content (typically `text/html`) |
| `filing.content_length` | int | Length of content in bytes |

---

### `GET /v1/financials/{ticker}`
Structured financial statements from XBRL data.

```
GET /v1/financials/AAPL?limit=3
```
```json
{
  "ticker": "AAPL",
  "cik": "0000320193",
  "name": "Apple Inc.",
  "currency": "USD",
  "income_statement": [
    {
      "fiscal_year": 2023,
      "period_end": "2023-09-30",
      "revenue": 383285000000,
      "net_income": 96995000000,
      "operating_income": 114301000000,
      "earnings_per_share_basic": 6.16,
      "earnings_per_share_diluted": 6.13
    }
  ],
  "balance_sheet": [
    {
      "fiscal_year": 2023,
      "period_end": "2023-09-30",
      "total_assets": 352583000000,
      "total_liabilities": 290437000000,
      "total_equity": 62146000000,
      "cash_and_equivalents": 29965000000
    }
  ],
  "cash_flow": [
    {
      "fiscal_year": 2023,
      "period_end": "2023-09-30",
      "operating_cash_flow": 110543000000,
      "investing_cash_flow": -3976000000,
      "financing_cash_flow": -108488000000,
      "free_cash_flow": 99584000000
    }
  ]
}
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 5 | Number of annual periods to return (1–20) |


## SEC Fair-Use Policy

The SEC requires that automated clients:

1. **Identify themselves** via `User-Agent` header — edit `_USER_AGENT` in `app/edgar_client.py` to include your name and email.
2. **Stay under 10 requests/second** across all machines.

The client already sets the `User-Agent` header on every request and enforces a per-process request limit using:

- `SEC_EDGAR_RATE_LIMIT_RPS` = `n` requests per 1 second (sliding window)
- default is `8` if unset or invalid

Examples:

```bash
# 5 calls per second
export SEC_EDGAR_RATE_LIMIT_RPS=5
uvicorn app.main:app --reload

# Docker compose
SEC_EDGAR_RATE_LIMIT_RPS=5 docker compose up -d
```

See [SEC developer resources](https://www.sec.gov/about/developer-resources) for full policy.

---

## Running Tests

```bash
pytest tests/ -v
```

All external HTTP calls are mocked; no network access required.


## Data Sources

All data is sourced exclusively from the SEC's official public APIs — no account or key needed:

| URL | Purpose |
|---|---|
| `https://www.sec.gov/files/company_tickers.json` | Ticker → CIK mapping (~10 000 companies) |
| `https://data.sec.gov/submissions/CIK{cik}.json` | Company metadata + filing history |
| `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | All XBRL financial facts |

The ticker map is cached in-process for 1 hour; individual company data is fetched on demand.
