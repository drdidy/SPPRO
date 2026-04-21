"""Lightweight options-provider bridge for live tastytrade lookups."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

import requests

try:
    from anyio import move_on_after, run as anyio_run
    from tastytrade import DXLinkStreamer, Session
    from tastytrade.dxfeed import Quote, Summary, Trade
    from tastytrade.instruments import Option, get_option_chain

    TASTYTRADE_SDK_AVAILABLE = True
except Exception:
    TASTYTRADE_SDK_AVAILABLE = False
    Session = None
    DXLinkStreamer = None
    Quote = None
    Trade = None
    Summary = None
    Option = None
    get_option_chain = None
    move_on_after = None
    anyio_run = None


PROVIDER_NAMES = ["none", "tastytrade"]
TASTYTRADE_TEST_KEYS = ["TASTYTRADE_IS_TEST", "tastytrade_is_test"]
TASTYTRADE_CLIENT_ID_KEYS = ["TASTYTRADE_CLIENT_ID", "tastytrade_client_id"]
TASTYTRADE_CLIENT_SECRET_KEYS = ["TASTYTRADE_CLIENT_SECRET", "tastytrade_client_secret"]
TASTYTRADE_REDIRECT_URI_KEYS = ["TASTYTRADE_REDIRECT_URI", "tastytrade_redirect_uri"]
TASTYTRADE_REFRESH_TOKEN_KEYS = ["TASTYTRADE_REFRESH_TOKEN", "tastytrade_refresh_token"]
TASTYTRADE_AUTH_CODE_KEYS = ["TASTYTRADE_AUTH_CODE", "tastytrade_auth_code"]
DEFAULT_USER_AGENT = "SPXProphet/1.0"


@dataclass
class OptionLookupRequest:
    """Prepared lookup payload for future options-provider queries."""

    trade_date: str
    session: str
    direction: str
    strike: int
    scenario_name: str = ""
    underlying_symbol: str = "SPX"
    option_type: str = "AUTO"

    def resolved_option_type(self) -> str:
        """Resolve the option type from the direction when needed."""

        if str(self.option_type).upper() in {"CALL", "PUT"}:
            return str(self.option_type).upper()
        return "CALL" if str(self.direction).upper() in {"CALL", "LONG"} else "PUT"

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable request payload."""

        payload = asdict(self)
        payload["resolved_option_type"] = self.resolved_option_type()
        return payload


@dataclass
class OptionQuoteRequest:
    """Prepared quote request payload for a future live quote lookup."""

    contract_symbol: str
    underlying_symbol: str = "SPX"
    trade_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable request payload."""

        return asdict(self)


@dataclass
class OptionCandidate:
    """Normalized contract candidate record."""

    symbol: str
    expiration_date: str
    strike: int
    right: str
    provider: str
    status: str = "preview"
    note: str = ""
    streamer_symbol: str = ""
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    mark: float | None = None
    volume: int | None = None
    open_interest: int | None = None


@dataclass
class ProviderStatus:
    """Summarize provider configuration and readiness."""

    provider_name: str
    readiness_state: str
    credentials_detected: bool
    options_mode_enabled: bool
    configured: bool
    live_mode_available: bool
    implementation_ready: bool
    status_label: str
    bridge_only: bool
    auth_mode: str = "none"
    active_environment: str = "sandbox"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable status payload."""

        return asdict(self)


class OptionsProviderBase:
    """Base interface for future options data providers."""

    provider_name = "none"

    def __init__(self, *, options_mode_enabled: bool = False) -> None:
        self.options_mode_enabled = bool(options_mode_enabled)

    def is_configured(self) -> bool:
        """Return True when the provider has enough external config to proceed."""

        return False

    def is_live_ready(self) -> bool:
        """Return True when the provider can attempt live requests safely."""

        return False

    def get_status(self) -> ProviderStatus:
        """Return provider status."""

        return ProviderStatus(
            provider_name=self.provider_name,
            readiness_state="disabled",
            credentials_detected=False,
            options_mode_enabled=self.options_mode_enabled,
            configured=False,
            live_mode_available=False,
            implementation_ready=False,
            status_label="Not configured",
            bridge_only=True,
            notes=["No live options provider is configured."],
        )

    def get_option_chain_snapshot(self, request: OptionLookupRequest) -> dict[str, Any]:
        """Return an option-chain snapshot when implemented."""

        return {
            "provider": self.provider_name,
            "request": request.to_dict(),
            "status": "unavailable",
            "contracts": [],
        }

    def get_option_quote(self, request: OptionQuoteRequest) -> dict[str, Any] | None:
        """Return a single option quote when implemented."""

        return {
            "provider": self.provider_name,
            "request": request.to_dict(),
            "status": "unavailable",
        }

    def find_candidate_contracts(self, request: OptionLookupRequest) -> list[dict[str, Any]]:
        """Return placeholder contract candidates when implemented."""

        return []


class NullOptionsProvider(OptionsProviderBase):
    """Disabled provider implementation."""

    provider_name = "none"


class TastytradeProviderSkeleton(OptionsProviderBase):
    """Tastytrade provider with live chain and quote lookup when configured."""

    provider_name = "tastytrade"

    def __init__(
        self,
        *,
        options_mode_enabled: bool = False,
        environment: Mapping[str, str] | None = None,
        secrets: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(options_mode_enabled=options_mode_enabled)
        self.environment = environment or os.environ
        self.secrets = secrets or {}
        self._session_token: str | None = None
        self._session_expiration: float = 0.0
        self._last_error: str | None = None

    @staticmethod
    def _build_diagnostics() -> dict[str, Any]:
        """Create a mutable diagnostics payload for a lookup run."""

        return {
            "login": {"success": False, "message": ""},
            "chain_lookup": {"success": False, "message": ""},
            "quote_lookup": {"success": False, "message": ""},
            "failure_stage": None,
            "failure_message": None,
            "provider_mode": None,
            "auth_mode": "none",
            "active_environment": "sandbox",
            "token_retrieval": {"success": False, "message": ""},
            "request": {},
            "symbol_resolution": {},
            "expiration_resolution": {},
            "strike_resolution": {},
        }

    def _get_external_value(self, *names: str) -> str | None:
        """Read a config value from environment variables or Streamlit secrets."""

        for name in names:
            value = self.environment.get(name)
            if value:
                return str(value)
            secret_value = self.secrets.get(name)
            if secret_value:
                return str(secret_value)
        return None

    def _detect_oauth_values(self) -> dict[str, bool]:
        """Detect whether OAuth credential fields are present."""

        client_id = self._get_external_value(*TASTYTRADE_CLIENT_ID_KEYS)
        client_secret = self._get_external_value(*TASTYTRADE_CLIENT_SECRET_KEYS)
        redirect_uri = self._get_external_value(*TASTYTRADE_REDIRECT_URI_KEYS)
        refresh_token = self._get_external_value(*TASTYTRADE_REFRESH_TOKEN_KEYS)
        auth_code = self._get_external_value(*TASTYTRADE_AUTH_CODE_KEYS)
        return {
            "client_id_detected": bool(client_id),
            "client_secret_detected": bool(client_secret),
            "redirect_uri_detected": bool(redirect_uri),
            "refresh_token_detected": bool(refresh_token),
            "auth_code_detected": bool(auth_code),
        }

    def _is_test_environment(self) -> bool:
        """Return True when sandbox mode is configured externally."""

        raw = str(self._get_external_value(*TASTYTRADE_TEST_KEYS) or "").strip().lower()
        return raw in {"1", "true", "yes", "sandbox", "cert"}

    def _base_url(self) -> str:
        """Return the configured tastytrade API base URL."""

        return "https://api.cert.tastyworks.com" if self._is_test_environment() else "https://api.tastyworks.com"

    def _oauth_token_url(self) -> str:
        """Return the configured OAuth token endpoint."""

        return f"{self._base_url()}/oauth/token"

    def _active_environment_label(self) -> str:
        """Return the current tastytrade environment label."""

        return "sandbox" if self._is_test_environment() else "production"

    def _resolve_oauth_auth_mode(self) -> str:
        """Determine the available OAuth grant mode."""

        refresh_token = self._get_external_value(*TASTYTRADE_REFRESH_TOKEN_KEYS)
        auth_code = self._get_external_value(*TASTYTRADE_AUTH_CODE_KEYS)
        redirect_uri = self._get_external_value(*TASTYTRADE_REDIRECT_URI_KEYS)
        client_id = self._get_external_value(*TASTYTRADE_CLIENT_ID_KEYS)
        if refresh_token:
            return "oauth_refresh_token"
        if auth_code and client_id and redirect_uri:
            return "oauth_authorization_code"
        return "oauth_unconfigured"

    def is_configured(self) -> bool:
        """Return True when external OAuth credentials are detected."""

        oauth_flags = self._detect_oauth_values()
        has_client_secret = oauth_flags["client_secret_detected"]
        has_refresh_flow = oauth_flags["refresh_token_detected"]
        has_auth_code_flow = (
            oauth_flags["client_id_detected"]
            and oauth_flags["auth_code_detected"]
            and oauth_flags["redirect_uri_detected"]
        )
        return has_client_secret and (has_refresh_flow or has_auth_code_flow)

    def is_live_ready(self) -> bool:
        """Return True when the provider can attempt a real live lookup safely."""

        return self.options_mode_enabled and self.is_configured() and TASTYTRADE_SDK_AVAILABLE

    def _retrieve_oauth_token(self, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
        """Retrieve an OAuth access token from tastytrade."""

        if self._session_token and time.time() < self._session_expiration - 60:
            if diagnostics is not None:
                diagnostics["login"] = {"success": True, "message": "Reused active OAuth access token."}
                diagnostics["token_retrieval"] = {"success": True, "message": "Reused active OAuth access token."}
            return {"access_token": self._session_token, "expires_in": max(int(self._session_expiration - time.time()), 0)}

        client_id = self._get_external_value(*TASTYTRADE_CLIENT_ID_KEYS)
        client_secret = self._get_external_value(*TASTYTRADE_CLIENT_SECRET_KEYS)
        redirect_uri = self._get_external_value(*TASTYTRADE_REDIRECT_URI_KEYS)
        refresh_token = self._get_external_value(*TASTYTRADE_REFRESH_TOKEN_KEYS)
        auth_code = self._get_external_value(*TASTYTRADE_AUTH_CODE_KEYS)
        auth_mode = self._resolve_oauth_auth_mode()
        if diagnostics is not None:
            diagnostics["auth_mode"] = auth_mode
            diagnostics["active_environment"] = self._active_environment_label()

        if not client_secret:
            raise RuntimeError("No tastytrade OAuth client secret detected.")

        payload: dict[str, Any]
        if refresh_token:
            payload = {
                "grant_type": "refresh_token",
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }
            if client_id:
                payload["client_id"] = client_id
        elif auth_code and client_id and redirect_uri:
            payload = {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": auth_code,
                "redirect_uri": redirect_uri,
            }
        else:
            raise RuntimeError("OAuth credentials are incomplete. Supply a refresh token, or client ID + auth code + redirect URI.")

        response = requests.post(
            self._oauth_token_url(),
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            timeout=12,
        )
        response.raise_for_status()
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError("OAuth token response returned no access token.")
        expires_in = int(body.get("expires_in", 900))
        self._session_token = str(token)
        self._session_expiration = time.time() + expires_in
        self._last_error = None
        if diagnostics is not None:
            diagnostics["login"] = {"success": True, "message": "Authenticated successfully with tastytrade OAuth."}
            diagnostics["token_retrieval"] = {"success": True, "message": "OAuth access token retrieved successfully."}
        return body

    def _build_sdk_session(self, diagnostics: dict[str, Any] | None = None) -> Session:
        """Build an authenticated SDK session from an OAuth token."""

        if not TASTYTRADE_SDK_AVAILABLE or Session is None:
            raise RuntimeError("tastytrade SDK is not installed.")

        token_response = self._retrieve_oauth_token(diagnostics)
        client_secret = self._get_external_value(*TASTYTRADE_CLIENT_SECRET_KEYS)
        refresh_token = self._get_external_value(*TASTYTRADE_REFRESH_TOKEN_KEYS) or "unused"
        sdk_session = Session(provider_secret=client_secret, refresh_token=refresh_token, is_test=self._is_test_environment(), timeout=12)
        sdk_session.session_token = str(token_response.get("access_token", ""))
        sdk_session.session_expiration = self._session_expiration
        sdk_session._client.headers.update(
            {
                "Authorization": f"Bearer {sdk_session.session_token}",
                "User-Agent": DEFAULT_USER_AGENT,
            }
        )
        return sdk_session

    @staticmethod
    def _normalize_decimal(value: Decimal | float | int | None) -> float | None:
        """Convert decimal-ish values to simple floats."""

        if value is None:
            return None
        return float(value)

    def _pick_expiration(
        self,
        chain: dict[date, list[Option]],
        request: OptionLookupRequest,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[date | None, list[Option]]:
        """Pick the nearest usable expiration for the lookup request."""

        if not chain:
            if diagnostics is not None:
                diagnostics["expiration_resolution"] = {
                    "requested_date": request.trade_date,
                    "returned_expirations": [],
                    "chosen_expiration": None,
                    "reason": "No expirations returned from option chain.",
                }
            return None, []
        target_date = date.fromisoformat(request.trade_date)
        eligible_dates = sorted(expiration for expiration in chain if expiration >= target_date)
        chosen_date = eligible_dates[0] if eligible_dates else sorted(chain.keys())[0]
        if diagnostics is not None:
            diagnostics["expiration_resolution"] = {
                "requested_date": request.trade_date,
                "returned_expirations": [expiration.isoformat() for expiration in sorted(chain.keys())[:20]],
                "chosen_expiration": chosen_date.isoformat(),
                "reason": "Nearest usable expiration on or after request date." if eligible_dates else "No future expiration found; used nearest available expiration.",
            }
        return chosen_date, chain.get(chosen_date, [])

    @staticmethod
    def _candidate_underlyings(request: OptionLookupRequest) -> list[str]:
        """Return underlying symbols to try for tastytrade chain resolution."""

        base = str(request.underlying_symbol or "").strip().upper() or "SPX"
        candidates = [base]
        if base == "SPX":
            candidates.append("SPXW")
        deduped: list[str] = []
        for symbol in candidates:
            if symbol not in deduped:
                deduped.append(symbol)
        return deduped

    @staticmethod
    def _select_nearest_contracts(options: list[Option], requested_strike: int, limit: int = 5) -> tuple[list[Option], list[int]]:
        """Select a small nearest-strike slice around the requested strike."""

        strike_map: dict[int, list[Option]] = {}
        for option in options:
            strike_key = int(float(option.strike_price))
            strike_map.setdefault(strike_key, []).append(option)

        available_strikes = sorted(strike_map.keys())
        ranked_strikes = sorted(
            available_strikes,
            key=lambda strike_value: (abs(strike_value - int(requested_strike)), strike_value),
        )
        selected_strikes = ranked_strikes[:limit]

        selected_options: list[Option] = []
        for strike_value in selected_strikes:
            selected_options.extend(
                sorted(
                    strike_map[strike_value],
                    key=lambda option: (option.days_to_expiration, float(option.strike_price)),
                )
            )
        return selected_options[:limit], selected_strikes

    async def _fetch_option_chain_async(self, request: OptionLookupRequest, diagnostics: dict[str, Any]) -> tuple[list[OptionCandidate], str]:
        """Fetch a real option chain slice and rank candidate contracts."""

        diagnostics["provider_mode"] = "test" if self._is_test_environment() else "live"
        diagnostics["active_environment"] = self._active_environment_label()
        diagnostics["request"] = request.to_dict()
        sdk_session = self._build_sdk_session(diagnostics)
        underlying_candidates = self._candidate_underlyings(request)
        diagnostics["symbol_resolution"] = {
            "requested_underlying": request.underlying_symbol,
            "underlying_candidates": underlying_candidates,
            "direction": request.direction,
            "option_type": request.resolved_option_type(),
            "requested_strike": request.strike,
            "lookup_attempts": [],
        }
        desired_type = request.resolved_option_type()
        desired_type_code = "C" if desired_type == "CALL" else "P"
        last_status = "no_contracts"

        for underlying_symbol in underlying_candidates:
            attempt: dict[str, Any] = {
                "underlying": underlying_symbol,
                "chain_loaded": False,
                "expiration_count": 0,
                "chosen_expiration": None,
                "filtered_contract_count": 0,
                "has_exact_strike": False,
                "nearby_strikes": [],
                "status": "pending",
                "reason": "",
            }
            try:
                option_chain = await get_option_chain(sdk_session, underlying_symbol)
                attempt["chain_loaded"] = True
                attempt["expiration_count"] = len(option_chain)
                diagnostics["chain_lookup"] = {"success": True, "message": f"Loaded option chain for {underlying_symbol}."}
                expiration_date, options = self._pick_expiration(option_chain, request, diagnostics)
                attempt["chosen_expiration"] = expiration_date.isoformat() if expiration_date else None
                if expiration_date is None or not options:
                    attempt["status"] = "no_contracts"
                    attempt["reason"] = "No usable expiration or contracts returned."
                    diagnostics["symbol_resolution"]["lookup_attempts"].append(attempt)
                    last_status = "no_contracts"
                    continue

                filtered = [
                    option
                    for option in options
                    if str(option.option_type).upper() == desired_type_code
                    and bool(option.active)
                    and not bool(option.is_closing_only)
                ]
                available_strikes = sorted({int(float(option.strike_price)) for option in filtered})
                attempt["filtered_contract_count"] = len(filtered)
                attempt["has_exact_strike"] = int(request.strike) in available_strikes
                attempt["nearby_strikes"] = available_strikes[:15]
                if not filtered:
                    attempt["status"] = "no_matching_contracts"
                    attempt["reason"] = f"No active {desired_type} contracts were available in the chosen expiration."
                    diagnostics["symbol_resolution"]["lookup_attempts"].append(attempt)
                    last_status = "no_matching_contracts"
                    continue

                selected, selected_strikes = self._select_nearest_contracts(filtered, int(request.strike), limit=5)
                diagnostics["symbol_resolution"]["normalized_underlying_used"] = underlying_symbol
                diagnostics["expiration_resolution"]["requested_date"] = request.trade_date
                diagnostics["expiration_resolution"]["chosen_expiration"] = expiration_date.isoformat()
                diagnostics["strike_resolution"] = {
                    "requested_strike": request.strike,
                    "exact_strike_exists": int(request.strike) in available_strikes,
                    "available_nearby_strikes": available_strikes[:15],
                    "selected_strikes": selected_strikes,
                    "reason": "Nearest available strikes were selected around the requested strike. Exact strike is optional.",
                }
                attempt["status"] = "ok"
                attempt["reason"] = "Contracts found using nearest-strike fallback."
                attempt["selected_strikes"] = selected_strikes
                diagnostics["symbol_resolution"]["lookup_attempts"].append(attempt)
                candidates = [
                    OptionCandidate(
                        symbol=option.symbol,
                        expiration_date=option.expiration_date.isoformat(),
                        strike=int(float(option.strike_price)),
                        right=desired_type,
                        provider=self.provider_name,
                        status="live",
                        note="",
                        streamer_symbol=option.streamer_symbol,
                    )
                    for option in selected
                ]
                return candidates, "ok"
            except Exception as exc:
                attempt["status"] = "error"
                attempt["reason"] = f"{exc.__class__.__name__}: {exc}"
                diagnostics["symbol_resolution"]["lookup_attempts"].append(attempt)
                last_status = "no_contracts"

        diagnostics["strike_resolution"] = {
            "requested_strike": request.strike,
            "exact_strike_exists": False,
            "available_nearby_strikes": [],
            "selected_strikes": [],
            "reason": "No matching contracts were found across the tested underlying symbols.",
        }
        if diagnostics["symbol_resolution"]["lookup_attempts"]:
            matches = [attempt for attempt in diagnostics["symbol_resolution"]["lookup_attempts"] if attempt["status"] == "ok"]
            diagnostics["symbol_resolution"]["matched_underlyings"] = [attempt["underlying"] for attempt in matches]
        return [], last_status

    async def _fetch_live_quotes_async(self, streamer_symbols: list[str], diagnostics: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Fetch quote, trade, and summary events for the supplied symbols."""

        sdk_session = self._build_sdk_session(diagnostics)
        symbols = [symbol for symbol in streamer_symbols if symbol]
        if not symbols:
            return {}

        quote_map: dict[str, Any] = {}
        trade_map: dict[str, Any] = {}
        summary_map: dict[str, Any] = {}

        async with sdk_session._client:
            async with DXLinkStreamer(sdk_session) as streamer:
                await streamer.subscribe(Quote, symbols)
                await streamer.subscribe(Trade, symbols)
                await streamer.subscribe(Summary, symbols)
                deadline = time.time() + 4.0
                while time.time() < deadline:
                    if len(quote_map) >= len(symbols) and len(trade_map) >= len(symbols) and len(summary_map) >= len(symbols):
                        break

                    if len(quote_map) < len(symbols):
                        with move_on_after(0.25):
                            event = await streamer.get_event(Quote)
                            quote_map[event.event_symbol] = event
                    if len(trade_map) < len(symbols):
                        with move_on_after(0.25):
                            event = await streamer.get_event(Trade)
                            trade_map[event.event_symbol] = event
                    if len(summary_map) < len(symbols):
                        with move_on_after(0.25):
                            event = await streamer.get_event(Summary)
                            summary_map[event.event_symbol] = event

        normalized: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            quote = quote_map.get(symbol)
            trade = trade_map.get(symbol)
            summary = summary_map.get(symbol)
            bid = self._normalize_decimal(getattr(quote, "bid_price", None))
            ask = self._normalize_decimal(getattr(quote, "ask_price", None))
            last = self._normalize_decimal(getattr(trade, "price", None))
            normalized[symbol] = {
                "bid": bid,
                "ask": ask,
                "last": last,
                "mark": round((bid + ask) / 2.0, 4) if bid is not None and ask is not None else None,
                "volume": getattr(trade, "day_volume", None),
                "open_interest": getattr(summary, "open_interest", None),
            }
        diagnostics["quote_lookup"] = {
            "success": True,
            "message": f"Fetched live quote payloads for {sum(1 for symbol in symbols if normalized.get(symbol))} contract(s).",
        }
        return normalized

    def get_status(self) -> ProviderStatus:
        """Return live lookup readiness for the tastytrade bridge."""

        credentials_detected = self.is_configured()
        live_ready = self.is_live_ready()
        auth_mode = self._resolve_oauth_auth_mode()
        active_environment = self._active_environment_label()
        notes = [
            "Credentials must come from environment variables or Streamlit secrets.",
            "This section supports live contract lookup and quotes only. No order execution is enabled.",
            f"Authentication mode: {auth_mode}.",
            f"Environment: {active_environment}.",
        ]
        if not TASTYTRADE_SDK_AVAILABLE:
            notes.append("The tastytrade Python SDK is not installed in this environment.")
        if self._is_test_environment():
            notes.append("Sandbox mode is enabled. Quotes may be delayed.")
        if self._last_error:
            notes.append(self._last_error)

        if not self.options_mode_enabled:
            readiness_state = "disabled"
            status_label = "Disabled"
        elif not credentials_detected:
            readiness_state = "no_credentials"
            status_label = "No credentials detected"
        elif not TASTYTRADE_SDK_AVAILABLE:
            readiness_state = "sdk_unavailable"
            status_label = "SDK unavailable"
        elif live_ready:
            readiness_state = "live_ready"
            status_label = "Live lookup ready"
        else:
            readiness_state = "bridge_only"
            status_label = "Bridge only"

        return ProviderStatus(
            provider_name=self.provider_name,
            readiness_state=readiness_state,
            credentials_detected=credentials_detected,
            options_mode_enabled=self.options_mode_enabled,
            configured=credentials_detected,
            live_mode_available=live_ready,
            implementation_ready=TASTYTRADE_SDK_AVAILABLE,
            status_label=status_label,
            bridge_only=not live_ready,
            auth_mode=auth_mode,
            active_environment=active_environment,
            notes=notes,
        )

    def get_option_chain_snapshot(self, request: OptionLookupRequest) -> dict[str, Any]:
        """Return a live or placeholder chain snapshot response."""

        if not self.is_live_ready():
            return {
                "provider": self.provider_name,
                "request": request.to_dict(),
                "status": "bridge_only",
                "contracts": self.find_candidate_contracts(request),
                "message": "Live lookup is unavailable. Showing prepared request only.",
                "diagnostics": {
                    "provider_mode": "test" if self._is_test_environment() else "live",
                    "auth_mode": self._resolve_oauth_auth_mode(),
                    "active_environment": self._active_environment_label(),
                    "request": request.to_dict(),
                    "failure_stage": "configuration",
                    "failure_message": "Provider is not configured for live lookup.",
                },
            }

        diagnostics = self._build_diagnostics()
        try:
            candidates, chain_status = anyio_run(self._fetch_option_chain_async, request, diagnostics)
            quote_map = anyio_run(self._fetch_live_quotes_async, [candidate.streamer_symbol for candidate in candidates], diagnostics) if candidates else {}
            normalized_contracts = []
            for candidate in candidates:
                quote_details = quote_map.get(candidate.streamer_symbol, {})
                normalized_contracts.append(
                    asdict(
                        OptionCandidate(
                            symbol=candidate.symbol,
                            expiration_date=candidate.expiration_date,
                            strike=candidate.strike,
                            right=candidate.right,
                            provider=candidate.provider,
                            status="live" if quote_details else "chain_only",
                            note="" if quote_details else "Quote unavailable",
                            streamer_symbol=candidate.streamer_symbol,
                            bid=quote_details.get("bid"),
                            ask=quote_details.get("ask"),
                            last=quote_details.get("last"),
                            mark=quote_details.get("mark"),
                            volume=quote_details.get("volume"),
                            open_interest=quote_details.get("open_interest"),
                        )
                    )
                )
            return {
                "provider": self.provider_name,
                "request": request.to_dict(),
                "status": "live" if normalized_contracts else chain_status,
                "contracts": normalized_contracts,
                "message": "Live candidate contracts loaded." if normalized_contracts else "No live contracts matched the lookup request.",
                "diagnostics": {
                    **diagnostics,
                    "failure_stage": (
                        None
                        if normalized_contracts
                        else (
                            "expiration resolution"
                            if chain_status == "no_contracts"
                            else "strike resolution"
                            if chain_status == "no_matching_contracts"
                            else None
                        )
                    ),
                    "failure_message": (
                        None
                        if normalized_contracts
                        else diagnostics.get("expiration_resolution", {}).get("reason")
                        if chain_status == "no_contracts"
                        else diagnostics.get("strike_resolution", {}).get("reason")
                        if chain_status == "no_matching_contracts"
                        else None
                    ),
                },
            }
        except Exception as exc:
            self._last_error = f"Live lookup failed: {exc.__class__.__name__}: {exc}"
            message = f"{exc.__class__.__name__}: {exc}"
            if not diagnostics["login"]["success"]:
                diagnostics["failure_stage"] = "auth/session"
            elif not diagnostics["chain_lookup"]["success"]:
                diagnostics["failure_stage"] = "chain lookup"
            elif not diagnostics["quote_lookup"]["success"]:
                diagnostics["failure_stage"] = "quote lookup"
            else:
                diagnostics["failure_stage"] = "connectivity"
            diagnostics["failure_message"] = message
            if not diagnostics["chain_lookup"]["message"]:
                diagnostics["chain_lookup"]["message"] = "Chain lookup did not complete."
            if not diagnostics["quote_lookup"]["message"]:
                diagnostics["quote_lookup"]["message"] = "Quote lookup did not complete."
            return {
                "provider": self.provider_name,
                "request": request.to_dict(),
                "status": "lookup_failed",
                "contracts": [],
                "message": "Live options lookup failed. Check provider configuration and connectivity.",
                "error": str(exc),
                "diagnostics": diagnostics,
            }

    def get_option_quote(self, request: OptionQuoteRequest) -> dict[str, Any] | None:
        """Return a single live option quote when possible."""

        if not self.is_live_ready():
            return {
                "provider": self.provider_name,
                "request": request.to_dict(),
                "status": "bridge_only",
                "message": "Live quote lookup is unavailable.",
            }

        try:
            diagnostics = self._build_diagnostics()
            quote_map = anyio_run(self._fetch_live_quotes_async, [request.contract_symbol], diagnostics)
            quote = quote_map.get(request.contract_symbol, {})
            return {
                "provider": self.provider_name,
                "request": request.to_dict(),
                "status": "live" if quote else "quote_unavailable",
                "diagnostics": diagnostics,
                **quote,
            }
        except Exception as exc:
            self._last_error = f"Quote lookup failed: {exc.__class__.__name__}: {exc}"
            return {
                "provider": self.provider_name,
                "request": request.to_dict(),
                "status": "quote_failed",
                "message": "Live option quote lookup failed.",
                "error": str(exc),
            }

    def find_candidate_contracts(self, request: OptionLookupRequest) -> list[dict[str, Any]]:
        """Return live candidates when possible, otherwise a safe placeholder row."""

        if self.is_live_ready():
            snapshot = self.get_option_chain_snapshot(request)
            contracts = snapshot.get("contracts") or []
            if contracts:
                return contracts

        option_type = request.resolved_option_type()
        candidate = OptionCandidate(
            symbol=f"{request.underlying_symbol} {request.trade_date} {option_type[0]}{int(request.strike)}",
            expiration_date=request.trade_date,
            strike=int(request.strike),
            right=option_type,
            provider=self.provider_name,
            note="Preview only. Live lookup unavailable.",
        )
        return [asdict(candidate)]


def load_options_provider(
    *,
    provider_name: str,
    options_mode_enabled: bool,
    secrets: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> OptionsProviderBase:
    """Load the selected provider implementation safely."""

    normalized_name = str(provider_name or "none").strip().lower()
    if normalized_name == "tastytrade":
        return TastytradeProviderSkeleton(
            options_mode_enabled=options_mode_enabled,
            environment=environment,
            secrets=secrets,
        )
    return NullOptionsProvider(options_mode_enabled=options_mode_enabled)
