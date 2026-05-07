"""
EdgarClient — async HTTP client wrapping data.sec.gov APIs.

SEC EDGAR public endpoints used (no API key needed):
  https://www.sec.gov/files/company_tickers.json        — ticker → CIK map
  https://data.sec.gov/submissions/CIK{cik}.json        — company metadata + filings
  https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json — all XBRL facts

Rate-limit: configurable via env var `SEC_EDGAR_RATE_LIMIT_RPS` as N requests
per 1 second (sliding window). Default is 8 req/s to stay under SEC guidance.
User-Agent header is set on every request (see SEC fair-use policy).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections import deque
from typing import Optional

import httpx

from app.models import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    CompanyInfo,
    CompanySearchResult,
    Filing,
    FilingContent,
    FilingContentResponse,
    FilingsResponse,
    FinancialsResponse,
    IncomeStatementPeriod,
)

# --------------------------------------------------------------------------
# SEC asks you to identify your application in User-Agent.
# Edit the name/email to reflect your deployment.
# --------------------------------------------------------------------------
_USER_AGENT = "SEC-EDGAR-Self-Hosted/1.0 (self-hosted; contact@example.com)"
_BASE = "https://data.sec.gov"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_RATE_LIMIT_RPS_ENV = "SEC_EDGAR_RATE_LIMIT_RPS"
_DEFAULT_RATE_LIMIT_RPS = 8

# XBRL concept names we care about, grouped by statement
_INCOME_CONCEPTS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsSold", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_basic": ["CommonStockSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
}

_BALANCE_CONCEPTS = {
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityAttributableToParent",
    ],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
}

_CASHFLOW_CONCEPTS = {
    "operating": ["NetCashProvidedByUsedInOperatingActivities"],
    "investing": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing": ["NetCashProvidedByUsedInFinancingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CapitalExpendituresIncurredButNotYetPaid",
    ],
}

SIC_DESCRIPTIONS = {
    "7372": "Prepackaged Software",
    "7371": "Computer Programming, Data Processing",
    "3674": "Semiconductors",
    "3661": "Telephone & Telegraph Apparatus",
    "6022": "State commercial banks",
    "2836": "Pharmaceutical Preparations",
    "5945": "Hobby, Toy & Game Shops",
    "7011": "Hotels and Motels",
    "5912": "Drug Stores and Proprietary Stores",
    "2911": "Petroleum Refining",
}


class EdgarClient:
    def __init__(self):
        self._http = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=30.0,
            follow_redirects=True,
        )
        self._rate_limit_rps = self._read_rate_limit_rps()
        self._rate_lock = asyncio.Lock()
        self._request_timestamps: deque[float] = deque()
        self._ticker_map: dict[str, dict] | None = None
        self._ticker_map_loaded_at: float = 0
        self._lock = asyncio.Lock()

    def _read_rate_limit_rps(self) -> int:
        raw_value = os.getenv(_RATE_LIMIT_RPS_ENV, str(_DEFAULT_RATE_LIMIT_RPS))
        try:
            parsed = int(raw_value)
        except ValueError:
            return _DEFAULT_RATE_LIMIT_RPS
        return parsed if parsed > 0 else _DEFAULT_RATE_LIMIT_RPS

    async def _acquire_rate_limit_slot(self) -> None:
        while True:
            async with self._rate_lock:
                now = time.monotonic()
                cutoff = now - 1.0

                while self._request_timestamps and self._request_timestamps[0] <= cutoff:
                    self._request_timestamps.popleft()

                if len(self._request_timestamps) < self._rate_limit_rps:
                    self._request_timestamps.append(now)
                    return

                oldest = self._request_timestamps[0]
                sleep_for = max(0.001, 1.0 - (now - oldest))

            await asyncio.sleep(sleep_for)

    async def _get_json(self, url: str) -> dict:
        await self._acquire_rate_limit_slot()
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Ticker → CIK map (cached for 1 hour)
    # ------------------------------------------------------------------

    async def _get_ticker_map(self) -> dict[str, dict]:
        async with self._lock:
            if self._ticker_map is None or (time.time() - self._ticker_map_loaded_at > 3600):
                raw = await self._get_json(_TICKERS_URL)
                # raw is {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, …}
                self._ticker_map = {
                    v["ticker"].upper(): v for v in raw.values()
                }
                self._ticker_map_loaded_at = time.time()
        return self._ticker_map

    async def _resolve_ticker(self, ticker: str) -> dict:
        """Return the ticker-map entry for a given ticker (raises KeyError if not found)."""
        tm = await self._get_ticker_map()
        if ticker not in tm:
            raise KeyError(ticker)
        return tm[ticker]

    @staticmethod
    def _pad_cik(cik_int: int) -> str:
        return str(cik_int).zfill(10)

    async def _get_submissions(self, cik: str) -> dict:
        url = f"{_BASE}/submissions/CIK{cik}.json"
        return await self._get_json(url)

    async def _get_company_facts(self, cik: str) -> dict:
        url = f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
        return await self._get_json(url)

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_company(self, ticker: str) -> CompanyInfo:
        entry = await self._resolve_ticker(ticker)
        cik = self._pad_cik(entry["cik_str"])
        subs = await self._get_submissions(cik)

        addresses = subs.get("addresses", {})

        def _addr(key: str) -> Optional[dict]:
            a = addresses.get(key, {})
            return {k: v for k, v in a.items() if v} or None

        sic = subs.get("sic")
        return CompanyInfo(
            ticker=ticker,
            cik=cik,
            name=subs.get("name", entry.get("title", ticker)),
            sic=str(sic) if sic else None,
            sic_description=SIC_DESCRIPTIONS.get(str(sic)) if sic else None,
            state_of_incorporation=subs.get("stateOfIncorporation"),
            fiscal_year_end=subs.get("fiscalYearEnd"),
            exchanges=subs.get("exchanges", []),
            tickers=subs.get("tickers", [ticker]),
            ein=subs.get("ein"),
            business_address=_addr("business"),
            mailing_address=_addr("mailing"),
            category=subs.get("category"),
        )

    async def search_companies(self, query: str, limit: int = 10) -> list[CompanySearchResult]:
        tm = await self._get_ticker_map()
        q = query.upper()
        results: list[CompanySearchResult] = []

        # Exact ticker match first
        if q in tm:
            e = tm[q]
            results.append(
                CompanySearchResult(
                    ticker=e["ticker"],
                    cik=self._pad_cik(e["cik_str"]),
                    name=e["title"],
                )
            )

        # Name prefix / substring matches
        for entry in tm.values():
            if len(results) >= limit:
                break
            ticker = entry["ticker"]
            name = entry.get("title", "").upper()
            if ticker == q:
                continue  # already added
            if name.startswith(q) or q in name or ticker.startswith(q):
                results.append(
                    CompanySearchResult(
                        ticker=ticker,
                        cik=self._pad_cik(entry["cik_str"]),
                        name=entry["title"],
                    )
                )

        return results[:limit]

    async def get_filings(
        self,
        ticker: str,
        form_type: Optional[str] = None,
        limit: int = 20,
    ) -> FilingsResponse:
        entry = await self._resolve_ticker(ticker)
        cik = self._pad_cik(entry["cik_str"])
        subs = await self._get_submissions(cik)

        recent = subs.get("filings", {}).get("recent", {})
        acc_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        forms = recent.get("form", [])
        primary_docs = recent.get("primaryDocument", [])
        is_xbrl = recent.get("isInlineXBRL", [])
        items = recent.get("items", [])

        filings: list[Filing] = []
        for i, acc in enumerate(acc_numbers):
            form = forms[i] if i < len(forms) else ""
            if form_type and form.upper() != form_type.upper():
                continue
            acc_clean = acc.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/"
            primary_doc = primary_docs[i] if i < len(primary_docs) else None
            doc_url = f"{filing_url}{primary_doc}" if primary_doc else None

            filings.append(
                Filing(
                    accession_number=acc,
                    filing_date=filing_dates[i] if i < len(filing_dates) else None,
                    report_date=report_dates[i] if i < len(report_dates) else None,
                    form=form,
                    primary_document=primary_doc,
                    filing_url=filing_url,
                    document_url=doc_url,
                    is_inline_xbrl=bool(is_xbrl[i]) if i < len(is_xbrl) else None,
                    items=items[i] if i < len(items) else None,
                )
            )
            if len(filings) >= limit:
                break

        return FilingsResponse(
            ticker=ticker,
            cik=cik,
            name=subs.get("name", entry.get("title", ticker)),
            total=len(filings),
            filings=filings,
        )

    async def get_filing_content(
        self,
        ticker: str,
        accession_number: str,
    ) -> FilingContentResponse:
        """
        Fetch the full text content of a specific SEC filing document.
        
        Args:
            ticker: Company ticker symbol
            accession_number: Accession number of the filing (e.g., "0000320193-23-000077")
        
        Returns:
            FilingContentResponse containing company info and filing content
        """
        entry = await self._resolve_ticker(ticker)
        cik = self._pad_cik(entry["cik_str"])
        subs = await self._get_submissions(cik)

        # Accept accession numbers in either dashed (0000000000-00-000000)
        # or non-dashed (000000000000000000) format.
        normalized_accession = re.sub(r"[^0-9A-Za-z]", "", accession_number).upper()
        if not normalized_accession:
            raise ValueError("Accession number is required")
        
        # Find the specific filing
        recent = subs.get("filings", {}).get("recent", {})
        acc_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        forms = recent.get("form", [])
        primary_docs = recent.get("primaryDocument", [])
        
        filing_index = None
        matched_accession = None
        for i, acc in enumerate(acc_numbers):
            if re.sub(r"[^0-9A-Za-z]", "", acc).upper() == normalized_accession:
                filing_index = i
                matched_accession = acc
                break
        
        if filing_index is None:
            raise ValueError(f"Filing with accession number '{accession_number}' not found")
        
        # Construct the document URL
        acc_clean = matched_accession.replace("-", "") if matched_accession else normalized_accession
        primary_doc = primary_docs[filing_index] if filing_index < len(primary_docs) else None
        
        if not primary_doc:
            raise ValueError(f"No primary document found for accession number '{accession_number}'")
        
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/"
        doc_url = f"{filing_url}{primary_doc}"
        
        # Fetch the actual content
        content = await self._fetch_text_content(doc_url)
        
        filing = FilingContent(
            accession_number=matched_accession or accession_number,
            filing_date=filing_dates[filing_index] if filing_index < len(filing_dates) else None,
            form=forms[filing_index] if filing_index < len(forms) else "UNKNOWN",
            primary_document=primary_doc,
            document_url=doc_url,
            content=content,
            content_type="text/html",
            content_length=len(content.encode('utf-8')),
        )
        
        return FilingContentResponse(
            ticker=ticker,
            cik=cik,
            name=subs.get("name", entry.get("title", ticker)),
            filing=filing,
        )

    async def _fetch_text_content(self, url: str) -> str:
        """
        Fetch and extract text content from a document URL.
        
        Args:
            url: URL to fetch content from
        
        Returns:
            Text content of the document
        """
        await self._acquire_rate_limit_slot()
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.text

    async def get_financials(self, ticker: str, limit: int = 5) -> FinancialsResponse:
        entry = await self._resolve_ticker(ticker)
        cik = self._pad_cik(entry["cik_str"])
        facts_data, subs = await asyncio.gather(
            self._get_company_facts(cik),
            self._get_submissions(cik),
        )

        us_gaap = facts_data.get("facts", {}).get("us-gaap", {})

        def _get_annual_values(concepts: list[str]) -> dict[str, float]:
            """Return {period_end: value} from the first concept that has data."""
            for concept in concepts:
                node = us_gaap.get(concept)
                if not node:
                    continue
                for unit_key, unit_facts in node.get("units", {}).items():
                    annual = [
                        f for f in unit_facts
                        if f.get("form") in ("10-K", "10-K/A")
                        and f.get("frame", "").startswith("CY")
                        and not f.get("frame", "").endswith("Q1")
                        and not f.get("frame", "").endswith("Q2")
                        and not f.get("frame", "").endswith("Q3")
                        and not f.get("frame", "").endswith("Q4")
                    ]
                    # deduplicate by end date, keep latest filed
                    by_end: dict[str, dict] = {}
                    for f in unit_facts:
                        if f.get("form") not in ("10-K", "10-K/A"):
                            continue
                        end = f.get("end", "")
                        filed = f.get("filed", "")
                        if end not in by_end or filed > by_end[end].get("filed", ""):
                            by_end[end] = f
                    if by_end:
                        return {end: d["val"] for end, d in sorted(by_end.items(), reverse=True)}
            return {}

        # ---- Income Statement ----
        rev = _get_annual_values(_INCOME_CONCEPTS["revenue"])
        cogs = _get_annual_values(_INCOME_CONCEPTS["cost_of_revenue"])
        gp = _get_annual_values(_INCOME_CONCEPTS["gross_profit"])
        oi = _get_annual_values(_INCOME_CONCEPTS["operating_income"])
        ni = _get_annual_values(_INCOME_CONCEPTS["net_income"])
        eps_b = _get_annual_values(_INCOME_CONCEPTS["eps_basic"])
        eps_d = _get_annual_values(_INCOME_CONCEPTS["eps_diluted"])
        shs = _get_annual_values(_INCOME_CONCEPTS["shares_basic"])

        all_periods = sorted(
            set(rev) | set(ni) | set(oi),
            reverse=True,
        )[:limit]

        income_stmt = []
        for period in all_periods:
            year = int(period[:4]) if period else None
            r = rev.get(period)
            c = cogs.get(period)
            income_stmt.append(
                IncomeStatementPeriod(
                    fiscal_year=year,
                    period_end=period,
                    revenue=r,
                    cost_of_revenue=c,
                    gross_profit=gp.get(period) or ((r - c) if r and c else None),
                    operating_income=oi.get(period),
                    net_income=ni.get(period),
                    earnings_per_share_basic=eps_b.get(period),
                    earnings_per_share_diluted=eps_d.get(period),
                    shares_outstanding_basic=shs.get(period),
                )
            )

        # ---- Balance Sheet ----
        assets = _get_annual_values(_BALANCE_CONCEPTS["total_assets"])
        liab = _get_annual_values(_BALANCE_CONCEPTS["total_liabilities"])
        equity = _get_annual_values(_BALANCE_CONCEPTS["total_equity"])
        cash = _get_annual_values(_BALANCE_CONCEPTS["cash"])
        curr_a = _get_annual_values(_BALANCE_CONCEPTS["current_assets"])
        curr_l = _get_annual_values(_BALANCE_CONCEPTS["current_liabilities"])
        ltd = _get_annual_values(_BALANCE_CONCEPTS["long_term_debt"])

        bs_periods = sorted(set(assets) | set(equity), reverse=True)[:limit]
        balance_sheet = [
            BalanceSheetPeriod(
                fiscal_year=int(p[:4]) if p else None,
                period_end=p,
                total_assets=assets.get(p),
                total_liabilities=liab.get(p),
                total_equity=equity.get(p),
                cash_and_equivalents=cash.get(p),
                total_current_assets=curr_a.get(p),
                total_current_liabilities=curr_l.get(p),
                long_term_debt=ltd.get(p),
            )
            for p in bs_periods
        ]

        # ---- Cash Flow ----
        op_cf = _get_annual_values(_CASHFLOW_CONCEPTS["operating"])
        inv_cf = _get_annual_values(_CASHFLOW_CONCEPTS["investing"])
        fin_cf = _get_annual_values(_CASHFLOW_CONCEPTS["financing"])
        capex = _get_annual_values(_CASHFLOW_CONCEPTS["capex"])

        cf_periods = sorted(set(op_cf) | set(inv_cf), reverse=True)[:limit]
        cash_flow = []
        for p in cf_periods:
            op = op_cf.get(p)
            cx = capex.get(p)
            cash_flow.append(
                CashFlowPeriod(
                    fiscal_year=int(p[:4]) if p else None,
                    period_end=p,
                    operating_cash_flow=op,
                    investing_cash_flow=inv_cf.get(p),
                    financing_cash_flow=fin_cf.get(p),
                    capital_expenditures=cx,
                    free_cash_flow=(op - cx) if op is not None and cx is not None else None,
                )
            )

        return FinancialsResponse(
            ticker=ticker,
            cik=cik,
            name=subs.get("name", entry.get("title", ticker)),
            income_statement=income_stmt,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
        )
