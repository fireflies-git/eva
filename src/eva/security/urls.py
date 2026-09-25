"""Validation helpers for outbound URLs.

The application receives URLs from Discord messages and from third party API
responses.  Parsing a URL is not enough to prevent SSRF: a hostname can resolve
to loopback or a private address, and an otherwise safe URL can redirect to one.
This module provides a small synchronous syntax check and an asynchronous check
that also resolves the hostname before a request is made.

Callers that follow redirects must call :func:`validate_url_for_request` for
each destination.  Browser callers should validate every request, including
subresources, because a public page can embed a private URL.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from aiohttp.abc import AbstractResolver, ResolveResult

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_DNS_TIMEOUT_SECONDS = 3.0
_MAX_URL_LENGTH = 8192
_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class URLPolicyError(ValueError):
    """Raised when a URL is not safe for an outbound request."""


@dataclass(frozen=True, slots=True)
class ValidatedURL:
    """A normalized URL plus its parsed components."""

    value: str
    parsed: SplitResult
    hostname: str


class PolicyResolver(AbstractResolver):
    """Resolve and validate the exact DNS answers used by aiohttp to connect.

    A separate URL preflight is insufficient for SSRF protection: a rebinding
    hostname can answer with a public address for validation and a private one
    when the HTTP connector resolves it again.  This resolver checks the
    connector's answers immediately before handing them to the socket layer.
    Use it with ``TCPConnector(use_dns_cache=False)`` and validate URL syntax
    before each request, including redirects.
    """

    def __init__(self, *, allow_private: bool = False) -> None:
        self._allow_private = allow_private

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        try:
            answers = await asyncio.wait_for(
                asyncio.to_thread(_resolve_records, host, port, family),
                timeout=_DEFAULT_DNS_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise URLPolicyError("URL hostname resolution timed out") from exc
        except OSError as exc:
            raise URLPolicyError("URL hostname could not be resolved") from exc

        if not answers:
            raise URLPolicyError("URL hostname has no addresses")

        records: list[ResolveResult] = []
        for address, answer_family, proto in answers:
            if not self._allow_private and _is_blocked_ip(address):
                raise URLPolicyError("URL resolves to a private or local network address")
            records.append(
                ResolveResult(
                    hostname=host,
                    host=str(address),
                    port=port,
                    family=answer_family,
                    proto=proto,
                    flags=socket.AI_NUMERICHOST,
                )
            )
        return records

    async def close(self) -> None:
        return None


def validate_url(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: frozenset[str] | set[str] | None = None,
) -> ValidatedURL:
    """Validate URL syntax and literal-address policy.

    This function does not perform DNS resolution and is safe to use in
    synchronous code.  Network-facing asynchronous code should use
    :func:`validate_url_for_request` instead so DNS answers are checked too.
    """

    if not isinstance(url, str):
        raise URLPolicyError("URL must be a string")
    value = url.strip()
    if not value:
        raise URLPolicyError("URL must not be empty")
    if len(value) > _MAX_URL_LENGTH:
        raise URLPolicyError("URL is too long")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise URLPolicyError("URL contains control characters")

    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        # Accessing .port catches malformed ports such as :99999.
        port = parsed.port
    except ValueError as exc:
        raise URLPolicyError("URL is malformed") from exc

    if scheme not in _ALLOWED_SCHEMES:
        raise URLPolicyError("URL scheme must be http or https")
    if not hostname:
        raise URLPolicyError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise URLPolicyError("URLs containing credentials are not allowed")
    if port is not None and not (1 <= port <= 65535):
        raise URLPolicyError("URL port is invalid")

    # A zone identifier is meaningful only for local IPv6 addresses.  Reject
    # it explicitly rather than relying on resolver-specific behavior.
    if "%" in hostname:
        raise URLPolicyError("IPv6 zone identifiers are not allowed")

    normalized_host = _normalize_hostname(hostname)
    if not allow_private and _is_blocked_hostname(normalized_host):
        raise URLPolicyError("Private or local network addresses are not allowed")

    if allowed_hosts is not None:
        normalized_allowed = {_normalize_hostname(item) for item in allowed_hosts}
        if normalized_host not in normalized_allowed:
            raise URLPolicyError("URL host is not on the outbound allowlist")

    return ValidatedURL(value=value, parsed=parsed, hostname=normalized_host)


async def validate_url_for_request(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: frozenset[str] | set[str] | None = None,
    dns_timeout_seconds: float = _DEFAULT_DNS_TIMEOUT_SECONDS,
) -> ValidatedURL:
    """Validate a URL immediately before making an outbound request.

    DNS resolution is performed off the event loop.  Every returned address
    must be globally routable unless ``allow_private`` is explicitly enabled.
    This check is intentionally repeated for redirects and browser requests to
    reduce DNS-rebinding and redirect-based SSRF risk.
    """

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                validate_url_for_request_sync,
                url,
                allow_private=allow_private,
                allowed_hosts=allowed_hosts,
            ),
            timeout=max(0.1, dns_timeout_seconds),
        )
    except TimeoutError as exc:
        raise URLPolicyError("URL hostname resolution timed out") from exc


def validate_url_for_request_sync(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: frozenset[str] | set[str] | None = None,
) -> ValidatedURL:
    """Synchronous URL validation for blocking downloader callbacks."""

    validated = validate_url(
        url,
        allow_private=allow_private,
        allowed_hosts=allowed_hosts,
    )
    if allow_private:
        return validated

    try:
        # ``getaddrinfo`` is blocking here because callers use this helper from
        # yt-dlp's synchronous request callbacks. The timeout is enforced by
        # the caller's bounded download runtime.
        addresses = _resolve_addresses(validated.hostname, validated.parsed.port)
    except OSError as exc:
        raise URLPolicyError("URL hostname could not be resolved") from exc

    if not addresses:
        raise URLPolicyError("URL hostname has no addresses")
    if any(_is_blocked_ip(address) for address in addresses):
        raise URLPolicyError("URL resolves to a private or local network address")
    return validated


def _resolve_addresses(hostname: str, port: int | None) -> set[_IPAddress]:
    """Resolve *hostname* to a set of IP addresses.

    ``getaddrinfo`` can return duplicate records and both IPv4/IPv6 tuples;
    normalize them before policy evaluation.
    """

    # DNS policy depends on the address, but an accurate service avoids odd
    # resolver behavior for hosts with port-specific records.
    service = port if port is not None else 443
    return {address for address, _, _ in _resolve_records(hostname, service, socket.AF_UNSPEC)}


def _resolve_records(
    hostname: str,
    port: int,
    family: socket.AddressFamily,
) -> list[tuple[_IPAddress, socket.AddressFamily, int]]:
    results = socket.getaddrinfo(
        hostname,
        port,
        family=family,
        type=socket.SOCK_STREAM,
    )
    addresses: list[tuple[_IPAddress, socket.AddressFamily, int]] = []
    for result in results:
        answer_family, _, proto, _, _ = result
        sockaddr = result[4]
        if not sockaddr:
            continue
        try:
            addresses.append((ipaddress.ip_address(sockaddr[0]), answer_family, proto))
        except ValueError:
            continue
    return addresses


def _normalize_hostname(hostname: str) -> str:
    normalized = hostname.rstrip(".").lower()
    if not normalized:
        raise URLPolicyError("URL hostname is invalid")
    try:
        # Convert internationalized hostnames to their ASCII form for stable
        # allowlist comparison.  Literal IP addresses pass through unchanged.
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise URLPolicyError("URL hostname is invalid") from exc


def _is_blocked_hostname(hostname: str) -> bool:
    if hostname in {"localhost", "localhost.localdomain", "broadcasthost"}:
        return True
    try:
        return _is_blocked_ip(ipaddress.ip_address(hostname))
    except ValueError:
        return False


def _is_blocked_ip(address: _IPAddress) -> bool:
    # is_global excludes private, loopback, link-local, multicast, reserved,
    # unspecified, and documentation ranges.  A few IPv4 shared ranges have
    # implementation-specific is_global behavior, so explicitly reject all
    # non-global addresses as well as the metadata endpoint.
    return not address.is_global


__all__ = [
    "URLPolicyError",
    "ValidatedURL",
    "PolicyResolver",
    "validate_url",
    "validate_url_for_request",
    "validate_url_for_request_sync",
]
