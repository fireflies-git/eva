"""Opt-in NopeCHA captcha solving for Discord challenges."""

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
from eva.security.urls import PolicyResolver, URLPolicyError, validate_url_for_request

logger = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 256 * 1024

CAPTCHA_TARGET_URL = "https://discord.com"


class NopeCHAError(RuntimeError):
    pass


class NopeCHAClient:
    """Solves ``discord.CaptchaRequired`` challenges via the NopeCHA token API.

    The application only constructs this client when an operator explicitly
    enables it and supplies an API key. Datacenter IPs may still be rejected.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = NOPECHA_API_URL,
        timeout_seconds: float = NOPECHA_TIMEOUT_SECONDS,
        poll_interval_seconds: float = NOPECHA_POLL_INTERVAL_SECONDS,
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(
                    resolver=PolicyResolver(allow_private=self._allow_private_outbound),
                    use_dns_cache=False,
                ),
            )

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
            await validate_url_for_request(
                self._api_url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
            async with self._session.post(
                self._api_url,
                json=payload,
                allow_redirects=False,
            ) as response:
                text = await _read_response_text(response, max_bytes=_MAX_RESPONSE_BYTES)
                if response.status != 200:
                    raise _error_for_status(response.status, text)
                data = _parse_json(text)
        except NopeCHAError:
            raise
        except TimeoutError as exc:
            raise NopeCHAError("NopeCHA job creation timed out") from exc
        except aiohttp.ClientError as exc:
            raise NopeCHAError("NopeCHA network error") from exc
        except URLPolicyError as exc:
            raise NopeCHAError(f"NopeCHA URL blocked by outbound policy: {exc}") from exc
        except Exception as exc:
            logger.warning(
                "NopeCHA job response handling failed error_type=%s",
                type(exc).__name__,
            )
            raise NopeCHAError("Invalid NopeCHA job response") from exc

        if not isinstance(data, dict):
            raise NopeCHAError("Invalid NopeCHA job response")
        job_id = data.get("data")
        if not isinstance(job_id, str) or not job_id:
            raise NopeCHAError("NopeCHA rejected the job")
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
                await validate_url_for_request(
                    self._api_url,
                    allow_private=self._allow_private_outbound,
                    allowed_hosts=self._allowed_hosts,
                )
                async with self._session.get(
                    self._api_url,
                    params=params,
                    allow_redirects=False,
                ) as response:
                    text = await _read_response_text(response, max_bytes=_MAX_RESPONSE_BYTES)
                    if response.status != 200:
                        raise _error_for_status(response.status, text)
                    data = _parse_json(text)
            except NopeCHAError:
                raise
            except TimeoutError as exc:
                raise NopeCHAError("NopeCHA poll timed out") from exc
            except aiohttp.ClientError as exc:
                raise NopeCHAError("NopeCHA network error") from exc
            except URLPolicyError as exc:
                raise NopeCHAError(f"NopeCHA URL blocked by outbound policy: {exc}") from exc
            except Exception as exc:
                logger.warning(
                    "NopeCHA poll response handling failed error_type=%s",
                    type(exc).__name__,
                )
                raise NopeCHAError("Invalid NopeCHA poll response") from exc

            if not isinstance(data, dict):
                raise NopeCHAError("Invalid NopeCHA poll response")
            error = data.get("error")
            if isinstance(error, str) and error:
                # Do not reflect arbitrary provider text into logs or Discord;
                # it can contain request metadata or secret-bearing URLs.
                raise NopeCHAError("NopeCHA rejected the captcha request")
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
    lowered = text.lower()
    if status == 403:
        return NopeCHAError(
            "NopeCHA banned this IP (BannedUser); captcha solving unavailable"
        )
    if status == 402 or "no credit" in lowered:
        return NopeCHAError("NopeCHA has no credit for this request")
    return NopeCHAError(f"NopeCHA HTTP {status}")


async def _read_response_text(response: aiohttp.ClientResponse, *, max_bytes: int) -> str:
    content = getattr(response, "content", None)
    if content is not None and hasattr(content, "iter_chunked"):
        chunks: list[bytes] = []
        total = 0
        async for chunk in content.iter_chunked(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise NopeCHAError("NopeCHA response exceeds configured size limit")
            chunks.append(chunk)
        raw = b"".join(chunks)
    elif content is not None and hasattr(content, "read"):
        raw = await content.read(max_bytes + 1)
    else:
        # Lightweight adapters may expose only ``text()``. Real aiohttp
        # responses take one of the bounded branches above.
        raw = (await response.text()).encode("utf-8")
    if len(raw) > max_bytes:
        raise NopeCHAError("NopeCHA response exceeds configured size limit")
    return raw.decode(getattr(response, "charset", None) or "utf-8", errors="replace")


def _parse_json(text: str) -> object:
    import json

    return json.loads(text)
