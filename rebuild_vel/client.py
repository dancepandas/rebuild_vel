"""Read-only client for the flow-data API with account rotation and retries."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, Iterator, Mapping, Optional

from .accounts import AccountPool

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://aiflow2.dashuiyun.cn:9999/prod-api"

#: Endpoints this project is allowed to call (read-only / export only).
READ_ENDPOINTS = frozenset({
    "/flow/originalDataFilterPage",
    "/flow/vDistribution",
    "/flow/stationSpeedLineDistribution",
    "/flow/speedLineDataExport",
    "/flow/procedureDataMergeExport",
    "/level/originalDataFilterPage",
    "/level/reportDataPage",
    "/flow/reportDataPage",
})

LOGIN_ENDPOINT = "/loginNoVerify"

TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
AUTH_STATUS = frozenset({401})
PERMANENT_STATUS = frozenset({400, 403, 404, 405, 409, 410, 422})

#: Business-level messages that mean "the platform's anti-duplicate guard
#: tripped" (提交去重).  Not an error in the data: the identical export was
#: seen moments ago, so the request is retried through the backoff loop
#: instead of failing the caller.
RETRYABLE_MESSAGES = ("不允许重复提交",)


class RemoteAPIError(RuntimeError):
    """The remote API rejected a request or returned malformed data."""


class AuthenticationError(RemoteAPIError):
    """Authentication failed permanently."""


class PermanentAPIError(RemoteAPIError):
    """Deterministic business error; retrying is pointless."""


class FlowClient:
    """Thin wrapper around ``requests`` with per-account tokens and backoff."""

    def __init__(
        self,
        accounts: AccountPool,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 60.0,
        max_attempts: int = 6,
        request_delay: float = 0.2,
        login_retry_after: float = 900.0,
        session: Any = None,
        sleep=time.sleep,
    ) -> None:
        if max_attempts < 1 or timeout <= 0 or request_delay < 0 or login_retry_after < 0:
            raise ValueError("invalid retry/timeout settings")
        if session is None:
            import requests

            session = requests.Session()
        self.base_url = base_url.rstrip("/")
        self.accounts = accounts
        self.timeout = float(timeout)
        self.max_attempts = int(max_attempts)
        self.request_delay = float(request_delay)
        self.login_retry_after = float(login_retry_after)
        self.session = session
        self.sleep = sleep
        # slot -> token
        self._tokens: Dict[int, str] = {}
        # slot -> monotonic timestamp until which login failures are not retried;
        # a suspended/expired account must never sink every Nth request
        self._cooldown_until: Dict[int, float] = {}
        self._last_request_at = 0.0

    # -- auth -------------------------------------------------------------
    def _login(self, slot: int, username: str, password: str) -> None:
        response = self.session.post(
            self.base_url + LOGIN_ENDPOINT,
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if getattr(response, "status_code", None) in PERMANENT_STATUS | AUTH_STATUS:
            raise AuthenticationError(f"login rejected with status {response.status_code}")
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise AuthenticationError("login response did not contain a token")
        self._tokens[slot] = str(token)

    def _ensure_slot(self) -> int:
        """Acquire a logged-in account slot, skipping ones whose login fails.

        A slot whose login is rejected goes into cooldown for
        ``login_retry_after`` seconds so a single suspended/expired account
        cannot fail every Nth request; the cooldown expires on its own in case
        the account is renewed on the platform side.
        """
        now = time.monotonic()
        for _ in range(len(self.accounts)):
            slot, username, password = self.accounts.next()
            if now < self._cooldown_until.get(slot, 0.0):
                continue
            if slot in self._tokens:
                return slot
            try:
                self._login(slot, username, password)
                self._cooldown_until.pop(slot, None)
                return slot
            except AuthenticationError:
                self._cooldown_until[slot] = now + self.login_retry_after
                logger.warning(
                    "account slot %s (%s) login failed; cooling down %.0fs",
                    slot, username, self.login_retry_after,
                )
        raise AuthenticationError("no account in the pool could log in")

    def _throttle(self) -> None:
        remaining = self.request_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleep(remaining)

    @staticmethod
    def _business_error(endpoint: str, payload: Mapping[str, Any]) -> RemoteAPIError:
        """Build the right error for a non-zero business code.

        Permanent for real business rejections (e.g. 测次没有过程数据文件);
        transient for the anti-duplicate guard, which fires on identical
        export resubmission and clears on its own.
        """
        msg = str(payload.get("msg", ""))
        kind = (
            RemoteAPIError
            if any(marker in msg for marker in RETRYABLE_MESSAGES)
            else PermanentAPIError
        )
        return kind(f"API {endpoint} returned code={payload.get('code')}: {msg}")

    # -- core -------------------------------------------------------------
    def post(self, endpoint: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        if endpoint not in READ_ENDPOINTS:
            raise PermissionError(f"endpoint is not in the read-only allowlist: {endpoint}")
        last_error: Optional[BaseException] = None
        attempt = 0
        slot: Optional[int] = None
        relogged = False
        while attempt < self.max_attempts:
            attempt += 1
            response = None
            try:
                if slot is None:
                    slot = self._ensure_slot()
                self._throttle()
                response = self.session.post(
                    self.base_url + endpoint,
                    json=dict(body),
                    headers={
                        "Authorization": f"Bearer {self._tokens[slot]}",
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout,
                )
                self._last_request_at = time.monotonic()
                status = getattr(response, "status_code", 200)
                if status in AUTH_STATUS:
                    self._tokens.pop(slot, None)
                    slot = None
                    if relogged:
                        raise AuthenticationError(f"authentication kept failing for {endpoint}")
                    relogged = True
                    continue
                if status in PERMANENT_STATUS:
                    raise PermanentAPIError(
                        f"API {endpoint} rejected the request with status {status}"
                    )
                if status in TRANSIENT_STATUS:
                    raise RemoteAPIError(f"API {endpoint} returned transient status {status}")
                response.raise_for_status()
                payload = response.json()
                code = payload.get("code")
                if code not in (0, 200):
                    # Some export endpoints return business codes for empty input.
                    raise self._business_error(endpoint, payload)
                return payload
            except (KeyboardInterrupt, SystemExit):
                raise
            except (PermanentAPIError, AuthenticationError):
                raise
            except BaseException as exc:  # noqa: BLE001 - network layer is unpredictable
                last_error = exc
                if attempt < self.max_attempts:
                    delay = min(30.0, 2.0 ** (attempt - 1)) + random.random() * 0.25
                    self.sleep(delay)
                slot = None  # next attempt takes a fresh account
        raise RemoteAPIError(
            f"request failed after {self.max_attempts} attempts: {endpoint}"
        ) from last_error

    def get_bytes(self, endpoint: str, body: Mapping[str, Any]) -> bytes:
        """POST an export endpoint and return the raw response body (xlsx)."""
        if endpoint not in READ_ENDPOINTS:
            raise PermissionError(f"endpoint is not in the allowlist: {endpoint}")
        last_error: Optional[BaseException] = None
        slot: Optional[int] = None
        for attempt in range(self.max_attempts):
            try:
                if slot is None:
                    slot = self._ensure_slot()
                self._throttle()
                response = self.session.post(
                    self.base_url + endpoint,
                    json=dict(body),
                    headers={
                        "Authorization": f"Bearer {self._tokens[slot]}",
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout,
                )
                self._last_request_at = time.monotonic()
                status = getattr(response, "status_code", 200)
                if status in AUTH_STATUS:
                    self._tokens.pop(slot, None)
                    slot = None
                    continue
                if status in PERMANENT_STATUS | TRANSIENT_STATUS:
                    raise RemoteAPIError(f"API {endpoint} returned status {status}")
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                body_bytes = response.content
                if "json" in content_type:
                    payload = response.json()
                    code = payload.get("code")
                    if code not in (0, 200):
                        raise self._business_error(endpoint, payload)
                    return b""
                if body_bytes[:2] != b"PK":
                    raise RemoteAPIError(f"API {endpoint} returned non-xlsx payload")
                return body_bytes
            except (KeyboardInterrupt, SystemExit):
                raise
            except PermanentAPIError:
                raise
            except BaseException as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_attempts - 1:
                    self.sleep(min(30.0, 2.0 ** attempt) + random.random() * 0.25)
                slot = None
        raise RemoteAPIError(
            f"export failed after {self.max_attempts} attempts: {endpoint}"
        ) from last_error

    # -- helpers ----------------------------------------------------------
    def paginate(
        self,
        endpoint: str,
        request: Mapping[str, Any],
        *,
        page_size: int = 500,
        start_page: int = 1,
    ) -> Iterator[tuple[int, Dict[str, Any]]]:
        if page_size < 1 or start_page < 1:
            raise ValueError("page size and start page must be positive")
        page = start_page
        while True:
            payload = self.post(
                endpoint, {"count": page_size, "page": page, "request": dict(request)}
            )
            yield page, payload
            info = payload.get("pageInfo") or {}
            pages = int(info.get("pages") or page)
            if page >= pages or not payload.get("data"):
                break
            page += 1

    def iter_measurements(
        self,
        station_code: str,
        device_code: str,
        begin_time: str,
        end_time: str,
        *,
        page_size: int = 500,
        start_page: int = 1,
        measure_result: int = 1,
    ) -> Iterator[tuple[int, Mapping[str, Any]]]:
        request = {
            "beginTime": begin_time,
            "endTime": end_time,
            "stationCode": station_code,
            "deviceCode": device_code,
            "measureResult": measure_result,
        }
        for page, payload in self.paginate(
            "/flow/originalDataFilterPage", request,
            page_size=page_size, start_page=start_page,
        ):
            for measurement in payload.get("data") or []:
                yield page, measurement
