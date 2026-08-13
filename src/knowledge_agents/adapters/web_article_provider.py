from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import re
import socket
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpcore
import httpx
from trafilatura import bare_extraction

from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import (
    AcquisitionRequest,
    CoverageReport,
    EvidenceBatch,
    EvidenceItem,
    SourceDescriptor,
)
from knowledge_agents.domain.enums import AcquisitionMethod, SourceType
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.ports.providers import KnowledgeSourceProvider

Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]
Fetcher = Callable[["ValidatedTarget", "WebArticleConfig"], Awaitable["WebResponse"]]
Clock = Callable[[], datetime]

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
TRANSIENT_STATUSES = frozenset({408, 425, 429})
WHITESPACE = re.compile(r"[ \t]+")


@dataclass(frozen=True, slots=True)
class WebArticleConfig:
    timeout_seconds: float = 30.0
    max_redirects: int = 5
    max_body_bytes: int = 5 * 1024 * 1024
    http_ports: tuple[int, ...] = (80,)
    https_ports: tuple[int, ...] = (443,)
    content_types: tuple[str, ...] = ("text/html", "application/xhtml+xml")
    user_agent: str = "knowledge-agents/0.1"
    failure_root: Path | None = Path("runtime/artifacts/web-failures")
    failure_retention: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        if self.failure_retention <= timedelta(0):
            raise ValueError("failure_retention must be positive")
        if not self.http_ports or not self.https_ports:
            raise ValueError("allowed ports must not be empty")


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WebResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class _ArticleDocument:
    canonical_ref: str
    title: str
    publisher: str
    text: str
    content_hash: str
    raw_size: int
    retrieved_at: datetime


class _CoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def __aiter__(self):
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, target: ValidatedTarget) -> None:
        self._target = target
        self._delegate = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.lower().rstrip(".") != self._target.host or port != self._target.port:
            raise DomainError(ErrorCode.SSRF_BLOCKED, "web.transport.target")
        last_error: Exception | None = None
        for address in self._target.addresses:
            try:
                return await self._delegate.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as error:
                last_error = error
        if last_error is None:
            raise DomainError(ErrorCode.SSRF_BLOCKED, "web.transport.addresses")
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise DomainError(ErrorCode.SSRF_BLOCKED, "web.transport.unix")


class _PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, target: ValidatedTarget) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
            network_backend=_PinnedNetworkBackend(target),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._pool.handle_async_request(
            httpcore.Request(
                method=request.method,
                url=httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class FailureHTMLStore:
    def __init__(self, root: Path, retention: timedelta) -> None:
        self._root = root
        self._retention = retention

    async def cleanup(self, now: datetime) -> None:
        await asyncio.to_thread(self._cleanup, now)

    async def retain(self, body: bytes, now: datetime) -> None:
        await asyncio.to_thread(self._retain, body, now)

    def _safe_root(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "web.failure_store")
        return self._root.resolve()

    def _cleanup(self, now: datetime) -> None:
        root = self._safe_root()
        cutoff = now.timestamp() - self._retention.total_seconds()
        for candidate in root.glob("failure-*.html"):
            if candidate.is_symlink() or candidate.stat().st_mtime <= cutoff:
                candidate.unlink(missing_ok=True)

    def _retain(self, body: bytes, now: datetime) -> None:
        self._cleanup(now)
        root = self._safe_root()
        digest = hashlib.sha256(body).hexdigest()[:20]
        target = root / f"failure-{int(now.timestamp())}-{digest}.html"
        if target.exists():
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".failure-",
                suffix=".tmp",
                dir=root,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            os.utime(target, (now.timestamp(), now.timestamp()))
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class WebArticleProvider(KnowledgeSourceProvider):
    def __init__(
        self,
        config: WebArticleConfig | None = None,
        *,
        resolver: Resolver | None = None,
        fetcher: Fetcher | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config or WebArticleConfig()
        self._resolver = resolver or _resolve_addresses
        self._fetcher = fetcher or _fetch_pinned
        self._clock = clock or (lambda: datetime.now(UTC))
        self._documents: dict[str, _ArticleDocument] = {}
        self._failure_store = (
            FailureHTMLStore(self.config.failure_root, self.config.failure_retention)
            if self.config.failure_root is not None
            else None
        )

    async def inspect(self, request: AcquisitionRequest) -> SourceDescriptor:
        now = self._clock()
        if self._failure_store is not None:
            await self._failure_store.cleanup(now)
        document = await self._load_document(str(request.url), now)
        source_id = _source_id(document.canonical_ref)
        self._documents[source_id] = document
        return SourceDescriptor(
            source_id=source_id,
            source_type=SourceType.WEB_ARTICLE,
            acquisition_method=AcquisitionMethod.STATIC_HTML,
            canonical_ref=document.canonical_ref,
            title=document.title,
            publisher=document.publisher,
            retrieved_at=document.retrieved_at,
            content_hash=document.content_hash,
            created_at=now,
        )

    async def acquire(
        self,
        source: SourceDescriptor,
        budget: ContextBudget,
    ) -> EvidenceBatch:
        if (
            source.source_type is not SourceType.WEB_ARTICLE
            or source.acquisition_method is not AcquisitionMethod.STATIC_HTML
        ):
            raise DomainError(ErrorCode.INVALID_REQUEST, "web.acquire.source")
        document = self._documents.pop(source.source_id, None)
        if document is None:
            document = await self._load_document(source.canonical_ref, self._clock())
        if document.content_hash != source.content_hash:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "web.acquire.content_hash")
        if document.raw_size > min(self.config.max_body_bytes, budget.max_source_bytes):
            raise DomainError(ErrorCode.BUDGET_EXCEEDED, "web.acquire.source_bytes")

        evidence_items = tuple(
            EvidenceItem(
                evidence_id=_evidence_id(index, paragraph),
                text=paragraph,
                locator=f"article:paragraph:{index:04d}",
                content_hash=hashlib.sha256(paragraph.encode("utf-8")).hexdigest(),
            )
            for index, paragraph in enumerate(_paragraphs(document.text), start=1)
        )
        return EvidenceBatch(
            source=source,
            evidence_items=evidence_items,
            coverage=CoverageReport(
                covered_topics=("article_body",),
                missing_topics=(),
                completeness=1.0,
            ),
            truncation=False,
            artifact_refs=(),
            created_at=document.retrieved_at,
        )

    async def _load_document(self, initial_url: str, now: datetime) -> _ArticleDocument:
        current_url = initial_url
        for redirect_count in range(self.config.max_redirects + 1):
            target = await _validate_target(current_url, self.config, self._resolver)
            try:
                response = await self._fetcher(target, self.config)
            except DomainError:
                raise
            except Exception as error:
                raise DomainError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    "web.fetch",
                    cause=error,
                ) from error

            if response.status_code in REDIRECT_STATUSES:
                location = _header(response.headers, "location")
                if location is None or redirect_count >= self.config.max_redirects:
                    raise DomainError(ErrorCode.INVALID_REQUEST, "web.redirect")
                current_url = urljoin(target.url, location)
                continue

            _validate_status(response.status_code)
            _validate_content_type(response.headers, self.config)
            if len(response.body) > self.config.max_body_bytes:
                raise DomainError(ErrorCode.INVALID_REQUEST, "web.body_limit")
            try:
                title, publisher, text = await asyncio.to_thread(
                    _extract_article,
                    response.body,
                    target.url,
                )
            except DomainError:
                if self._failure_store is not None:
                    await self._failure_store.retain(response.body, now)
                raise
            return _ArticleDocument(
                canonical_ref=target.url,
                title=title,
                publisher=publisher,
                text=text,
                content_hash=hashlib.sha256(response.body).hexdigest(),
                raw_size=len(response.body),
                retrieved_at=now,
            )
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.redirect")


async def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as error:
        raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "web.dns", cause=error) from error
    return tuple(sorted({str(record[4][0]) for record in records}))


async def _validate_target(
    raw_url: str,
    config: WebArticleConfig,
    resolver: Resolver,
) -> ValidatedTarget:
    normalized, scheme, host, port = _normalize_url(raw_url, config)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = await resolver(host, port)
    else:
        addresses = (str(literal),)
    if not addresses:
        raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "web.dns")
    normalized_addresses: set[str] = set()
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise DomainError(ErrorCode.SSRF_BLOCKED, "web.dns.address", cause=error) from error
        if not _is_public_address(address):
            raise DomainError(ErrorCode.SSRF_BLOCKED, "web.dns.address")
        normalized_addresses.add(str(address))
    return ValidatedTarget(
        url=normalized,
        scheme=scheme,
        host=host,
        port=port,
        addresses=tuple(sorted(normalized_addresses)),
    )


def _normalize_url(raw_url: str, config: WebArticleConfig) -> tuple[str, str, str, int]:
    if len(raw_url) > 2_048 or "\r" in raw_url or "\n" in raw_url:
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.url")
    parsed = urlsplit(raw_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.url.scheme")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.url.authority")
    if parsed.hostname is None:
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.url.host")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port or (443 if scheme == "https" else 80)
    except (UnicodeError, ValueError) as error:
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.url.authority", cause=error) from error
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise DomainError(ErrorCode.SSRF_BLOCKED, "web.url.host")
    allowed_ports = config.https_ports if scheme == "https" else config.http_ports
    if port not in allowed_ports:
        raise DomainError(ErrorCode.SSRF_BLOCKED, "web.url.port")
    display_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    authority = display_host if port == default_port else f"{display_host}:{port}"
    return (
        urlunsplit((scheme, authority, parsed.path or "/", parsed.query, "")),
        scheme,
        host,
        port,
    )


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    candidate = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    checked = candidate or address
    return bool(
        checked.is_global
        and not checked.is_private
        and not checked.is_reserved
        and not checked.is_loopback
        and not checked.is_link_local
        and not checked.is_multicast
        and not checked.is_unspecified
    )


async def _fetch_pinned(target: ValidatedTarget, config: WebArticleConfig) -> WebResponse:
    transport = _PinnedTransport(target)
    try:
        async with (
            httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(config.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Connection": "close",
                    "User-Agent": config.user_agent,
                },
            ) as client,
            client.stream("GET", target.url) as response,
        ):
            headers = {key.lower(): value for key, value in response.headers.items()}
            if response.status_code in REDIRECT_STATUSES or not 200 <= response.status_code < 300:
                return WebResponse(response.status_code, headers, b"")
            _validate_content_type(headers, config)
            content_length = _header(headers, "content-length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError as error:
                    raise DomainError(
                        ErrorCode.INVALID_REQUEST,
                        "web.content_length",
                        cause=error,
                    ) from error
                if declared_size < 0 or declared_size > config.max_body_bytes:
                    raise DomainError(ErrorCode.INVALID_REQUEST, "web.body_limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > config.max_body_bytes:
                    raise DomainError(ErrorCode.INVALID_REQUEST, "web.body_limit")
            return WebResponse(response.status_code, headers, bytes(body))
    except DomainError:
        raise
    except Exception as error:
        raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "web.fetch", cause=error) from error


def _validate_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code in {401, 403}:
        raise DomainError(ErrorCode.ACCESS_DENIED, "web.status")
    if status_code in TRANSIENT_STATUSES or status_code >= 500:
        raise DomainError(ErrorCode.PROVIDER_UNAVAILABLE, "web.status")
    raise DomainError(ErrorCode.INVALID_REQUEST, "web.status")


def _validate_content_type(headers: Mapping[str, str], config: WebArticleConfig) -> None:
    content_type = (_header(headers, "content-type") or "").split(";", 1)[0].strip().lower()
    if content_type not in config.content_types:
        raise DomainError(ErrorCode.INVALID_REQUEST, "web.content_type")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _extract_article(body: bytes, canonical_ref: str) -> tuple[str, str, str]:
    try:
        document = bare_extraction(
            body,
            url=canonical_ref,
            favor_precision=True,
            include_comments=False,
            include_images=False,
            include_links=False,
            include_tables=True,
            deduplicate=False,
            with_metadata=True,
        )
    except Exception as error:
        raise DomainError(
            ErrorCode.CONTRACT_VALIDATION_FAILED, "web.extract", cause=error
        ) from error
    if document is None:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "web.extract")
    extracted = document if isinstance(document, dict) else document.as_dict()
    text = _normalize_text(str(extracted.get("text") or ""))
    if not text:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "web.extract")
    host = urlsplit(canonical_ref).hostname or "web-article"
    title = _single_line(str(extracted.get("title") or "")) or host
    publisher = (
        _single_line(str(extracted.get("sitename") or extracted.get("hostname") or "")) or host
    )
    return title, publisher, text


def _normalize_text(value: str) -> str:
    lines = [WHITESPACE.sub(" ", line).strip() for line in value.replace("\r", "\n").split("\n")]
    return "\n\n".join(line for line in lines if line)


def _single_line(value: str) -> str:
    return WHITESPACE.sub(" ", value.replace("\r", " ").replace("\n", " ")).strip()


def _paragraphs(text: str) -> tuple[str, ...]:
    paragraphs = tuple(part.strip() for part in text.split("\n\n") if part.strip())
    if not paragraphs:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "web.evidence")
    return paragraphs


def _source_id(canonical_ref: str) -> str:
    digest = hashlib.sha256(canonical_ref.encode("utf-8")).hexdigest()
    return f"web-{digest[:24]}"


def _evidence_id(index: int, paragraph: str) -> str:
    digest = hashlib.sha256(paragraph.encode("utf-8")).hexdigest()
    return f"web-evidence-{index:04d}-{digest[:16]}"
