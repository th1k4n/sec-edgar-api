"""
Tests for the SEC EDGAR Data API.
Run with:  pytest tests/ -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.edgar_client import EdgarClient

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures: mock data matching data.sec.gov shapes
# ---------------------------------------------------------------------------

MOCK_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    "2": {"cik_str": 1018724, "ticker": "AMZN", "title": "Amazon.com Inc."},
}

MOCK_SUBMISSIONS = {
    "cik": "0000320193",
    "name": "Apple Inc.",
    "sic": "3674",
    "stateOfIncorporation": "CA",
    "fiscalYearEnd": "0930",
    "exchanges": ["Nasdaq"],
    "tickers": ["AAPL"],
    "ein": "94-2404110",
    "category": "Large accelerated filer",
    "addresses": {
        "business": {"street1": "One Apple Park Way", "city": "Cupertino", "stateOrCountry": "CA"},
        "mailing": {"street1": "One Apple Park Way", "city": "Cupertino", "stateOrCountry": "CA"},
    },
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-24-000006", "0000320193-23-000077"],
            "filingDate": ["2024-02-02", "2023-11-03"],
            "reportDate": ["2023-12-30", "2023-09-30"],
            "form": ["10-Q", "10-K"],
            "primaryDocument": ["aapl-20231230.htm", "aapl-20230930.htm"],
            "isInlineXBRL": [1, 1],
            "items": ["", ""],
        }
    },
}

MOCK_FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "label": "Revenue",
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 383285000000, "form": "10-K", "filed": "2023-11-03", "accn": "x"},
                        {"end": "2022-09-30", "val": 394328000000, "form": "10-K", "filed": "2022-10-28", "accn": "x"},
                        {"end": "2021-09-30", "val": 365817000000, "form": "10-K", "filed": "2021-10-29", "accn": "x"},
                    ]
                },
            },
            "NetIncomeLoss": {
                "label": "Net Income",
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 96995000000, "form": "10-K", "filed": "2023-11-03", "accn": "x"},
                        {"end": "2022-09-30", "val": 99803000000, "form": "10-K", "filed": "2022-10-28", "accn": "x"},
                    ]
                },
            },
            "Assets": {
                "label": "Total Assets",
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 352583000000, "form": "10-K", "filed": "2023-11-03", "accn": "x"},
                    ]
                },
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "label": "Operating Cash Flow",
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 110543000000, "form": "10-K", "filed": "2023-11-03", "accn": "x"},
                    ]
                },
            },
        }
    },
}


# ---------------------------------------------------------------------------
# Helper to patch the edgar_client methods
# ---------------------------------------------------------------------------

def _patch_client(ticker_map=None, submissions=None, facts=None):
    """Returns a context manager that patches EdgarClient internals."""
    patches = []

    if ticker_map is not None:
        patches.append(
            patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value=ticker_map)
        )
    if submissions is not None:
        patches.append(
            patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=submissions)
        )
    if facts is not None:
        patches.append(
            patch.object(EdgarClient, "_get_company_facts", new_callable=AsyncMock, return_value=facts)
        )

    return patches


# ---------------------------------------------------------------------------
# GET /v1/company/{ticker}
# ---------------------------------------------------------------------------

class TestGetCompany:
    def _run(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                return client.get("/v1/company/AAPL")

    def test_status_200(self):
        r = self._run()
        assert r.status_code == 200

    def test_ticker_returned(self):
        r = self._run()
        assert r.json()["ticker"] == "AAPL"

    def test_cik_zero_padded(self):
        r = self._run()
        assert r.json()["cik"] == "0000320193"

    def test_name_populated(self):
        r = self._run()
        assert "Apple" in r.json()["name"]

    def test_sic_populated(self):
        r = self._run()
        assert r.json()["sic"] == "3674"

    def test_fiscal_year_end(self):
        r = self._run()
        assert r.json()["fiscal_year_end"] == "0930"

    def test_unknown_ticker_404(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={}):
            r = client.get("/v1/company/ZZZZ")
        assert r.status_code == 404

    def test_case_insensitive_ticker(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                r = client.get("/v1/company/aapl")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/company?q=
# ---------------------------------------------------------------------------

class TestSearchCompanies:
    def _run(self, q="apple", limit=10):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            k: v for k, v in {
                "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                "MSFT": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            }.items()
        }):
            return client.get(f"/v1/company?q={q}&limit={limit}")

    def test_status_200(self):
        assert self._run().status_code == 200

    def test_returns_list(self):
        assert isinstance(self._run().json(), list)

    def test_exact_ticker_match(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }):
            r = client.get("/v1/company?q=AAPL")
        results = r.json()
        assert any(c["ticker"] == "AAPL" for c in results)

    def test_name_search(self):
        r = self._run(q="apple")
        results = r.json()
        assert any("Apple" in c["name"] for c in results)

    def test_limit_respected(self):
        r = self._run(limit=1)
        assert len(r.json()) <= 1

    def test_missing_q_422(self):
        r = client.get("/v1/company")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/filings/{ticker}
# ---------------------------------------------------------------------------

class TestGetFilings:
    def _run(self, form=None, limit=20):
        url = f"/v1/filings/AAPL?limit={limit}"
        if form:
            url += f"&form={form}"
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                return client.get(url)

    def test_status_200(self):
        assert self._run().status_code == 200

    def test_has_filings_list(self):
        data = self._run().json()
        assert "filings" in data
        assert isinstance(data["filings"], list)

    def test_filing_has_expected_fields(self):
        filing = self._run().json()["filings"][0]
        assert "accession_number" in filing
        assert "form" in filing
        assert "filing_date" in filing

    def test_filing_url_present(self):
        filing = self._run().json()["filings"][0]
        assert filing["filing_url"].startswith("https://www.sec.gov")

    def test_form_filter(self):
        data = self._run(form="10-K").json()
        for f in data["filings"]:
            assert f["form"] == "10-K"

    def test_limit_respected(self):
        data = self._run(limit=1).json()
        assert len(data["filings"]) <= 1

    def test_unknown_ticker_404(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={}):
            r = client.get("/v1/filings/ZZZZ")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/filings/{ticker}/{accession_number}
# ---------------------------------------------------------------------------

class TestGetFilingContent:
    def _run(self, ticker="AAPL", accession="0000320193-23-000077"):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                with patch.object(EdgarClient, "_fetch_text_content", new_callable=AsyncMock, return_value="<html><body>Test filing content</body></html>"):
                    return client.get(f"/v1/filings/{ticker}/{accession}")

    def test_status_200(self):
        r = self._run()
        assert r.status_code == 200

    def test_has_company_info(self):
        data = self._run().json()
        assert data["ticker"] == "AAPL"
        assert data["cik"] == "0000320193"
        assert "Apple" in data["name"]

    def test_has_filing_content(self):
        data = self._run().json()
        assert "filing" in data
        filing = data["filing"]
        assert "content" in filing
        assert "accession_number" in filing

    def test_filing_metadata_populated(self):
        filing = self._run().json()["filing"]
        assert filing["accession_number"] == "0000320193-23-000077"
        assert filing["form"] == "10-K"
        assert filing["filing_date"] == "2023-11-03"
        assert filing["primary_document"] == "aapl-20230930.htm"

    def test_content_length_calculated(self):
        filing = self._run().json()["filing"]
        assert filing["content_length"] > 0
        assert filing["content_length"] == len("<html><body>Test filing content</body></html>".encode('utf-8'))

    def test_content_type_html(self):
        filing = self._run().json()["filing"]
        assert filing["content_type"] == "text/html"

    def test_document_url_present(self):
        filing = self._run().json()["filing"]
        assert "https://www.sec.gov" in filing["document_url"]
        assert filing["primary_document"] in filing["document_url"]

    def test_unknown_ticker_404(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={}):
            r = client.get("/v1/filings/ZZZZ/0000320193-23-000077")
        assert r.status_code == 404

    def test_invalid_accession_404(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                r = client.get("/v1/filings/AAPL/0000000000-00-000000")
        assert r.status_code == 404

    def test_accession_without_dash_supported(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                with patch.object(EdgarClient, "_fetch_text_content", new_callable=AsyncMock, return_value="<html>content</html>"):
                    r = client.get("/v1/filings/AAPL/000032019323000077")
        assert r.status_code == 200
        assert r.json()["filing"]["accession_number"] == "0000320193-23-000077"

    def test_case_insensitive_accession(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                with patch.object(EdgarClient, "_fetch_text_content", new_callable=AsyncMock, return_value="<html>content</html>"):
                    # Try with lowercase accession number
                    r = client.get("/v1/filings/AAPL/0000320193-23-000077")
        assert r.status_code == 200

    def test_content_retrieved(self):
        data = self._run().json()
        filing = data["filing"]
        assert "<html>" in filing["content"]
        assert "Test filing content" in filing["content"]


# ---------------------------------------------------------------------------
# GET /v1/financials/{ticker}
# ---------------------------------------------------------------------------

class TestGetFinancials:
    def _run(self, limit=5):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={
            "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }):
            with patch.object(EdgarClient, "_get_submissions", new_callable=AsyncMock, return_value=MOCK_SUBMISSIONS):
                with patch.object(EdgarClient, "_get_company_facts", new_callable=AsyncMock, return_value=MOCK_FACTS):
                    return client.get(f"/v1/financials/AAPL?limit={limit}")

    def test_status_200(self):
        assert self._run().status_code == 200

    def test_has_income_statement(self):
        data = self._run().json()
        assert "income_statement" in data
        assert len(data["income_statement"]) > 0

    def test_revenue_populated(self):
        stmt = self._run().json()["income_statement"][0]
        assert stmt["revenue"] is not None
        assert stmt["revenue"] > 0

    def test_has_balance_sheet(self):
        data = self._run().json()
        assert "balance_sheet" in data

    def test_has_cash_flow(self):
        data = self._run().json()
        assert "cash_flow" in data

    def test_period_end_format(self):
        data = self._run().json()
        pe = data["income_statement"][0]["period_end"]
        assert re.match(r"\d{4}-\d{2}-\d{2}", pe)

    def test_limit_respected(self):
        data = self._run(limit=2).json()
        assert len(data["income_statement"]) <= 2

    def test_unknown_ticker_404(self):
        with patch.object(EdgarClient, "_get_ticker_map", new_callable=AsyncMock, return_value={}):
            r = client.get("/v1/financials/ZZZZ")
        assert r.status_code == 404

    def test_currency_usd(self):
        assert self._run().json()["currency"] == "USD"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
