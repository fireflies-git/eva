"""NopeCHA captcha solving for Discord challenges (IP free tier by default)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
import discord

from eva.constants import (
    NOPECHA_API_URL,
    NOPECHA_POLL_INTERVAL_SECONDS,
    NOPECHA_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

CAPTCHA_TARGET_URL = "https://discord.com"


class NopeCHAError(RuntimeError):
    pass


class NopeCHAClient:
    """Solves ``discord.CaptchaRequired`` challenges via the NopeCHA token API.

    Without an API key the free tier is used, which is quota'd by the request
    IP (about 100 solves/day). Datacenter IPs may be rejected with a 403.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = NOPECHA_API_URL,
        timeout_seconds: float = NOPECHA_TIMEOUT_SECONDS,
        poll_interval_seconds: float = NOPECHA_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def handle_captcha(
        self,
        exception: discord.CaptchaRequired,
        client: discord.Client,
    ) -> str:
        """``discord.Client(captcha_handler=...)``-compatible entry point."""
        return await self.solve(exception)

    async def solve(self, exception: discord.CaptchaRequired) -> str:
        payload = _build_job_payload(exception, api_key=self._api_key)
        job_id = await self._create_job(payload)
        return await self._poll_job(job_id)

    async def _create_job(self, payload: dict[str, Any]) -> str:
        if self._session is None:
            raise NopeCHAError("NopeCHA client is not started")
        try:
            async with self._session.post(self._api_url, json=payload) as response:
                text = await response.text()
                if response.status != 200:
                    raise _error_for_status(response.status, text)
                data = await response.json()
        except NopeCHAError:
            raise
        except TimeoutError as exc:
            raise NopeCHAError("NopeCHA job creation timed out") from exc
        except aiohttp.ClientError as exc:
            raise NopeCHAError(f"NopeCHA network error: {exc}") from exc
        except Exception as exc:
            raise NopeCHAError(f"Invalid NopeCHA job response: {exc}") from exc

        if not isinstance(data, dict):
            raise NopeCHAError("Invalid NopeCHA job response")
        job_id = data.get("data")
        if not isinstance(job_id, str) or not job_id:
            raise NopeCHAError(f"NopeCHA rejected the job: {data!r}")
        return job_id

    async def _poll_job(self, job_id: str) -> str:
        if self._session is None:
            raise NopeCHAError("NopeCHA client is not started")
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NopeCHAError("NopeCHA captcha solve timed out")

            params: dict[str, str] = {"id": job_id}
            if self._api_key:
                params["key"] = self._api_key
            try:
                async with self._session.get(self._api_url, params=params) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise _error_for_status(response.status, text)
                    data = await response.json()
            except NopeCHAError:
                raise
            except TimeoutError as exc:
                raise NopeCHAError("NopeCHA poll timed out") from exc
            except aiohttp.ClientError as exc:
                raise NopeCHAError(f"NopeCHA network error: {exc}") from exc
            except Exception as exc:
                raise NopeCHAError(f"Invalid NopeCHA poll response: {exc}") from exc

            if not isinstance(data, dict):
                raise NopeCHAError("Invalid NopeCHA poll response")
            error = data.get("error")
            if isinstance(error, str) and error:
                raise NopeCHAError(f"NopeCHA error: {error}")
            solution = data.get("data")
            if isinstance(solution, str) and solution:
                return solution

            await asyncio.sleep(min(self._poll_interval_seconds, max(remaining, 0.0)))


def _build_job_payload(
    exception: discord.CaptchaRequired,
    *,
    api_key: str | None,
) -> dict[str, Any]:
    service = exception.service
    if service == "hcaptcha":
        task: dict[str, object] = {
            "sitekey": exception.sitekey,
            "url": CAPTCHA_TARGET_URL,
        }
        if exception.rqdata:
            task["rqdata"] = exception.rqdata
        payload: dict[str, Any] = {"type": "hcaptcha", "task": task}
    elif service in ("recaptcha", "recaptcha_enterprise"):
        task = {
            "sitekey": exception.sitekey,
            "url": CAPTCHA_TARGET_URL,
        }
        if service == "recaptcha_enterprise":
            task["enterprise"] = True
        payload = {"type": "recaptcha2", "task": task}
    else:
        raise NopeCHAError(f"Unsupported captcha service: {service}")

    if api_key:
        payload["key"] = api_key
    return payload


def _error_for_status(status: int, text: str) -> NopeCHAError:
    snippet = text[:200]
    lowered = text.lower()
    if status == 403:
        return NopeCHAError(
            "NopeCHA banned this IP (BannedUser); captcha solving unavailable"
        )
    if status == 402 or "no credit" in lowered:
        return NopeCHAError(f"NopeCHA has no credit for this request: {snippet}")
    return NopeCHAError(f"NopeCHA HTTP {status}: {snippet}")
