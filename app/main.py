"""
SEC EDGAR Data API — Self-hosted replacement for RapidAPI SEC EDGAR Data API
Pulls directly from data.sec.gov (free, no API key required).

Endpoints mirrored:
  GET /v1/company/{ticker}                    — Company info (CIK, SIC, state, fiscal year end)
  GET /v1/company?q={query}                   — Search companies by ticker or name
  GET /v1/filings/{ticker}                    — SEC filing history (10-K, 10-Q, 8-K, …)
  GET /v1/filings/{ticker}/{accession_number} — Filing document content
  GET /v1/financials/{ticker}                 — Financial statements (income, balance sheet, cash flow)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import asyncio
import re
from functools import lru_cache
from typing import Optional

from app.edgar_client import EdgarClient
from app.models import (
    CompanyInfo,
    CompanySearchResult,
    FilingsResponse,
    FilingContentResponse,
    FinancialsResponse,
)

app = FastAPI(
    title="SEC EDGAR Data API",
    description=(
        "Self-hosted REST API for SEC EDGAR financial data. "
        "Data sourced directly from data.sec.gov — no third-party intermediary."
    ),
    version="1.0.0",
    contact={"name": "Self-hosted", "url": "https://www.sec.gov/edgar/sec-api-documentation"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

client = EdgarClient()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(
    "/v1/company/{ticker}",
    response_model=CompanyInfo,
    summary="Company info by ticker",
    tags=["Company"],
)
async def get_company(ticker: str):
    """
    Return basic company metadata: CIK, official name, SIC code, state of
    incorporation, fiscal-year-end month, exchanges, and tickers.
    """
    ticker = ticker.upper().strip()
    try:
        return await client.get_company(ticker)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get(
    "/v1/company",
    response_model=list[CompanySearchResult],
    summary="Search companies by name or ticker",
    tags=["Company"],
)
async def search_companies(
    q: str = Query(..., min_length=1, description="Ticker symbol or company name fragment"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Full-text search across all ~10 000 registered SEC filers.
    Returns matches sorted by relevance (exact ticker first, then name prefix).
    """
    try:
        return await client.search_companies(q.strip(), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get(
    "/v1/filings/{ticker}",
    response_model=FilingsResponse,
    summary="SEC filing history",
    tags=["Filings"],
)
async def get_filings(
    ticker: str,
    form_type: Optional[str] = Query(
        None,
        alias="form",
        description="Filter by form type, e.g. 10-K, 10-Q, 8-K",
    ),
    limit: int = Query(20, ge=1, le=200),
):
    """
    Returns the most recent SEC filings for a company.  Optionally filter by
    form type.  Each record includes the accession number, filing date, report
    date, form type, and a direct URL to the filing on SEC.gov.
    """
    ticker = ticker.upper().strip()
    try:
        return await client.get_filings(ticker, form_type=form_type, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get(
    "/v1/financials/{ticker}",
    response_model=FinancialsResponse,
    summary="Financial statements",
    tags=["Financials"],
)
async def get_financials(
    ticker: str,
    limit: int = Query(5, ge=1, le=20, description="Number of annual periods to return"),
):
    """
    Returns structured financial data extracted from XBRL filings:
    - **Income statement**: Revenue, Net Income, Operating Income, EPS
    - **Balance sheet**: Total Assets, Total Liabilities, Stockholders' Equity
    - **Cash flow**: Operating, Investing, Financing cash flows

    Values are in USD. Periods are annual (10-K) by default.
    """
    ticker = ticker.upper().strip()
    try:
        return await client.get_financials(ticker, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get(
    "/v1/filings/{ticker}/{accession_number}",
    response_model=FilingContentResponse,
    summary="Get filing document content",
    tags=["Filings"],
)
async def get_filing_content(
    ticker: str,
    accession_number: str,
):
    """
    Fetch the full text content of a specific SEC filing document.
    
    This endpoint allows custom models to retrieve detailed content from a filing
    by referencing the accession number obtained from the `/v1/filings/{ticker}`
    lookup endpoint.
    
    Args:
        ticker: Company ticker symbol (e.g., "AAPL")
        accession_number: Accession number from filing metadata (e.g., "0000320193-23-000077")
    
    Returns:
        FilingContentResponse with company info and complete filing document content
    
    Example:
        1. Call GET /v1/filings/AAPL to get available filings and accession numbers
        2. Use the accession_number from the response
        3. Call GET /v1/filings/AAPL/0000320193-23-000077 to fetch full document content
    """
    ticker = ticker.upper().strip()
    try:
        return await client.get_filing_content(ticker, accession_number)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/healthz", include_in_schema=False)
async def health():
    return {"status": "ok"}
