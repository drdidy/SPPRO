"""Lightweight options-provider bridge for future live integrations."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


PROVIDER_NAMES = ["none", "tastytrade"]


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
    """Placeholder contract candidate record."""

    symbol: str
    expiration_date: str
    strike: int
    right: str
    provider: str
    status: str = "preview"
    note: str = ""


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


def rank_candidate_contracts(candidates: list[dict[str, Any]], target_strike: int) -> list[dict[str, Any]]:
    """Score and rank candidate contracts by practical trade readiness.

    Criteria: strike proximity, spread width, volume, open interest.
    Returns candidates with added 'rank_score' and 'readiness' fields.
    """
    scored = []
    for contract in candidates:
        score = 0.0
        readiness_notes = []

        # Strike proximity (primary)
        strike_dist = abs(int(contract.get("strike", target_strike)) - target_strike)
        if strike_dist == 0:
            score += 50
        elif strike_dist <= 5:
            score += 40
        elif strike_dist <= 10:
            score += 20

        # Bid-ask spread
        bid = float(contract.get("bid", 0) or 0)
        ask = float(contract.get("ask", 0) or 0)
        if bid > 0 and ask > 0:
            spread = ask - bid
            if spread < 0.05:
                score += 30
                readiness_notes.append("tight spread")
            elif spread < 0.15:
                score += 15
                readiness_notes.append("acceptable spread")
            else:
                readiness_notes.append("wide spread")
        else:
            readiness_notes.append("incomplete quote")

        # Liquidity (volume + open interest)
        volume = int(contract.get("volume", 0) or 0)
        open_interest = int(contract.get("open_interest", 0) or 0)
        liquidity = volume + (open_interest * 0.5)
        if liquidity > 100:
            score += 15
            readiness_notes.append("good liquidity")
        elif liquidity > 10:
            readiness_notes.append("acceptable liquidity")
        else:
            readiness_notes.append("thin liquidity")

        contract_copy = dict(contract)
        contract_copy["rank_score"] = round(score, 1)
        contract_copy["readiness"] = "; ".join(readiness_notes) if readiness_notes else "complete"
        scored.append(contract_copy)

    return sorted(scored, key=lambda x: x["rank_score"], reverse=True)


class TastytradeProviderSkeleton(OptionsProviderBase):
    """Tastytrade-ready skeleton with safe credential detection only."""

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

    def _detect_credential_values(self) -> dict[str, bool]:
        """Detect whether external credential fields are present.

        Returns only boolean flags — never logs credential values.
        Credentials are read from environment variables or Streamlit secrets only.
        """

        env_username = bool(self.environment.get("TASTYTRADE_USERNAME"))
        env_password = bool(self.environment.get("TASTYTRADE_PASSWORD"))

        secret_username = bool(self.secrets.get("TASTYTRADE_USERNAME") or self.secrets.get("tastytrade_username"))
        secret_password = bool(self.secrets.get("TASTYTRADE_PASSWORD") or self.secrets.get("tastytrade_password"))

        return {
            "username_detected": env_username or secret_username,
            "password_detected": env_password or secret_password,
        }

    def is_configured(self) -> bool:
        """Return True when external credentials are detected."""

        credential_flags = self._detect_credential_values()
        return credential_flags["username_detected"] and credential_flags["password_detected"]

    def is_live_ready(self) -> bool:
        """Return False until live connection logic is implemented."""

        return False

    def get_status(self) -> ProviderStatus:
        """Return configuration-only status for the tastytrade bridge.

        Credential detection is safe: only boolean flags are returned, never actual secret values.
        """

        credentials_detected = self.is_configured()
        live_ready = self.is_live_ready()

        notes = [
            "Credentials must come from environment variables or Streamlit secrets only.",
            "Credential values are never logged; only presence flags are returned.",
            "Live login, live chain retrieval, and live quotes are not implemented yet in this bridge.",
        ]
        if not self.options_mode_enabled:
            readiness_state = "disabled"
            status_label = "Disabled"
            notes.append("Options mode is disabled in app settings.")
        elif not credentials_detected:
            readiness_state = "no_credentials"
            status_label = "No credentials detected"
            notes.append("Options mode is enabled, but external tastytrade credentials were not detected.")
        elif credentials_detected and not live_ready:
            readiness_state = "credentials_detected_not_connected"
            status_label = "Credentials detected, bridge only"
            notes.append("Credentials were detected, but no live tastytrade connection has been implemented yet.")
        else:
            readiness_state = "live_ready"
            status_label = "Live ready"

        return ProviderStatus(
            provider_name=self.provider_name,
            readiness_state=readiness_state,
            credentials_detected=credentials_detected,
            options_mode_enabled=self.options_mode_enabled,
            configured=credentials_detected,
            live_mode_available=live_ready,
            implementation_ready=True,
            status_label=status_label,
            bridge_only=not live_ready,
            notes=notes,
        )

    def get_option_chain_snapshot(self, request: OptionLookupRequest) -> dict[str, Any]:
        """Return a safe placeholder chain snapshot response."""

        return {
            "provider": self.provider_name,
            "request": request.to_dict(),
            "status": "bridge_only",
            "contracts": self.find_candidate_contracts(request),
            "note": "Tastytrade live chain retrieval is not implemented yet.",
        }

    def get_option_quote(self, request: OptionQuoteRequest) -> dict[str, Any] | None:
        """Return a safe placeholder quote response."""

        return {
            "provider": self.provider_name,
            "request": request.to_dict(),
            "status": "bridge_only",
            "note": "Tastytrade live quote retrieval is not implemented yet.",
        }

    def find_candidate_contracts(self, request: OptionLookupRequest) -> list[dict[str, Any]]:
        """Return a ranked placeholder candidate list for UI preview purposes."""

        option_type = request.resolved_option_type()
        option_right = "C" if option_type == "CALL" else "P"
        candidate = OptionCandidate(
            symbol=f"{request.underlying_symbol} {request.trade_date} {option_right}{int(request.strike)}",
            expiration_date=request.trade_date,
            strike=int(request.strike),
            right=option_right,
            provider=self.provider_name,
            note="Preview only. Live chain lookup is not implemented yet.",
        )
        candidates = [asdict(candidate)]
        return rank_candidate_contracts(candidates, int(request.strike))


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
