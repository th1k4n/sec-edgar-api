"""Pydantic response models for the SEC EDGAR Data API."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

class CompanyInfo(BaseModel):
    ticker: str
    cik: str = Field(..., description="10-digit Central Index Key, zero-padded")
    name: str
    sic: Optional[str] = Field(None, description="Standard Industrial Classification code")
    sic_description: Optional[str] = None
    state_of_incorporation: Optional[str] = None
    fiscal_year_end: Optional[str] = Field(None, description="MMDD, e.g. '0930' for Sep 30")
    exchanges: list[str] = []
    tickers: list[str] = []
    ein: Optional[str] = Field(None, description="Employer Identification Number")
    business_address: Optional[dict] = None
    mailing_address: Optional[dict] = None
    category: Optional[str] = None


class CompanySearchResult(BaseModel):
    ticker: str
    cik: str
    name: str


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------

class Filing(BaseModel):
    accession_number: str
    filing_date: Optional[str] = None
    report_date: Optional[str] = None
    form: str
    primary_document: Optional[str] = None
    filing_url: Optional[str] = Field(None, description="Direct URL to the filing index on SEC.gov")
    document_url: Optional[str] = Field(None, description="Direct URL to the primary document")
    is_inline_xbrl: Optional[bool] = None
    items: Optional[str] = None


class FilingsResponse(BaseModel):
    ticker: str
    cik: str
    name: str
    total: int
    filings: list[Filing]


class FilingContent(BaseModel):
    """Filing document content and metadata."""
    accession_number: str
    filing_date: Optional[str] = None
    form: str
    primary_document: Optional[str] = None
    document_url: Optional[str] = None
    content: str = Field(..., description="Full text content of the filing document")
    content_type: str = Field(default="text/html", description="MIME type of the content")
    content_length: int = Field(default=0, description="Length of content in bytes")


class FilingContentResponse(BaseModel):
    """Response for filing content retrieval."""
    ticker: str
    cik: str
    name: str
    filing: FilingContent


# ---------------------------------------------------------------------------
# Financials
# ---------------------------------------------------------------------------

class IncomeStatementPeriod(BaseModel):
    fiscal_year: Optional[int] = None
    period_end: Optional[str] = None
    form: Optional[str] = None
    revenue: Optional[float] = None
    cost_of_revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    earnings_per_share_basic: Optional[float] = None
    earnings_per_share_diluted: Optional[float] = None
    shares_outstanding_basic: Optional[float] = None


class BalanceSheetPeriod(BaseModel):
    fiscal_year: Optional[int] = None
    period_end: Optional[str] = None
    form: Optional[str] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    total_current_assets: Optional[float] = None
    total_current_liabilities: Optional[float] = None
    long_term_debt: Optional[float] = None


class CashFlowPeriod(BaseModel):
    fiscal_year: Optional[int] = None
    period_end: Optional[str] = None
    form: Optional[str] = None
    operating_cash_flow: Optional[float] = None
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    capital_expenditures: Optional[float] = None
    free_cash_flow: Optional[float] = None


class FinancialsResponse(BaseModel):
    ticker: str
    cik: str
    name: str
    currency: str = "USD"
    income_statement: list[IncomeStatementPeriod] = []
    balance_sheet: list[BalanceSheetPeriod] = []
    cash_flow: list[CashFlowPeriod] = []
