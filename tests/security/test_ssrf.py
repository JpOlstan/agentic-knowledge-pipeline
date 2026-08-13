from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

import httpcore
import pytest
from pydantic import ValidationError

from knowledge_agents.adapters.web_article_provider import (
    ValidatedTarget,
    WebArticleConfig,
    WebArticleProvider,
    WebResponse,
    _PinnedNetworkBackend,
)
from knowledge_agents.domain.contracts import AcquisitionRequest
from knowledge_agents.domain.errors import DomainError, ErrorCode

PUBLIC_IPV4 = "93.184.216.34"
PUBLIC_IPV6 = "2606:4700:4700::1111"


class RecordingFetcher:
    def __init__(self, responses: Iterable[WebResponse]) -> None:
        self.responses = list(responses)
        self.targets: list[ValidatedTarget] = []

    async def __call__(
        self,
        target: ValidatedTarget,
        _: WebArticleConfig,
    ) -> WebResponse:
        self.targets.append(target)
        return self.responses.pop(0)


def request(url: str) -> AcquisitionRequest:
    return AcquisitionRequest(url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/article",
        "https://example.com/article#fragment",
        "https://example.com:8443/article",
        "http://127.0.0.1/article",
        "http://10.0.0.1/article",
        "http://169.254.169.254/latest/meta-data",
        "http://192.0.2.1/article",
        "http://224.0.0.1/article",
        "http://[::1]/article",
        "http://[fe80::1]/article",
        "http://[::ffff:127.0.0.1]/article",
    ],
)
def test_unsafe_url_never_reaches_fetcher(tmp_path: Path, url: str) -> None:
    async def resolver(_: str, __: int) -> tuple[str, ...]:
        return (PUBLIC_IPV4,)

    async def scenario() -> None:
        fetcher = RecordingFetcher([])
        provider = WebArticleProvider(
            WebArticleConfig(failure_root=tmp_path),
            resolver=resolver,
            fetcher=fetcher,
        )
        with pytest.raises(DomainError) as captured:
            await provider.inspect(request(url))
        assert captured.value.code in {ErrorCode.INVALID_REQUEST, ErrorCode.SSRF_BLOCKED}
        assert fetcher.targets == []
        assert url not in str(captured.value)

    asyncio.run(scenario())


def test_request_contract_rejects_non_http_scheme() -> None:
    with pytest.raises(ValidationError):
        request("ftp://example.com/article")


@pytest.mark.parametrize(
    "addresses",
    [
        (PUBLIC_IPV4, "10.0.0.1"),
        (PUBLIC_IPV6, "fc00::1"),
        ("100.64.0.1",),
        ("0.0.0.0",),
        ("::",),
    ],
)
def test_every_dns_answer_must_be_public(tmp_path: Path, addresses: tuple[str, ...]) -> None:
    async def resolver(_: str, __: int) -> tuple[str, ...]:
        return addresses

    async def scenario() -> None:
        fetcher = RecordingFetcher([])
        provider = WebArticleProvider(
            WebArticleConfig(failure_root=tmp_path),
            resolver=resolver,
            fetcher=fetcher,
        )
        with pytest.raises(DomainError) as captured:
            await provider.inspect(request("https://example.com/article"))
        assert captured.value.code is ErrorCode.SSRF_BLOCKED
        assert fetcher.targets == []

    asyncio.run(scenario())


def test_redirect_dns_rebinding_is_blocked_before_second_request(tmp_path: Path) -> None:
    answers = iter(((PUBLIC_IPV4,), ("127.0.0.1",)))

    async def resolver(_: str, __: int) -> tuple[str, ...]:
        return next(answers)

    async def scenario() -> None:
        fetcher = RecordingFetcher(
            [WebResponse(302, {"location": "https://example.com/next"}, b"")]
        )
        provider = WebArticleProvider(
            WebArticleConfig(failure_root=tmp_path),
            resolver=resolver,
            fetcher=fetcher,
        )

        with pytest.raises(DomainError) as captured:
            await provider.inspect(request("https://example.com/start"))

        assert captured.value.code is ErrorCode.SSRF_BLOCKED
        assert len(fetcher.targets) == 1
        assert fetcher.targets[0].addresses == (PUBLIC_IPV4,)

    asyncio.run(scenario())


def test_redirect_limit_is_five_and_each_hop_is_revalidated(tmp_path: Path) -> None:
    calls = 0

    async def resolver(_: str, __: int) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return (PUBLIC_IPV4,)

    async def scenario() -> None:
        fetcher = RecordingFetcher(
            [WebResponse(302, {"location": "/again"}, b"") for _ in range(6)]
        )
        provider = WebArticleProvider(
            WebArticleConfig(failure_root=tmp_path, max_redirects=5),
            resolver=resolver,
            fetcher=fetcher,
        )

        with pytest.raises(DomainError) as captured:
            await provider.inspect(request("https://example.com/start"))

        assert captured.value.code is ErrorCode.INVALID_REQUEST
        assert captured.value.operation == "web.redirect"
        assert len(fetcher.targets) == 6
        assert calls == 6

    asyncio.run(scenario())


def test_pinned_backend_connects_to_validated_ip_without_resolving_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Delegate:
        def __init__(self) -> None:
            self.hosts: list[str] = []
            self.stream = object()

        async def connect_tcp(self, host: str, *_: object, **__: object) -> object:
            self.hosts.append(host)
            return self.stream

    delegate = Delegate()
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: delegate)
    target = ValidatedTarget(
        url="https://example.com/article",
        scheme="https",
        host="example.com",
        port=443,
        addresses=(PUBLIC_IPV4,),
    )

    async def scenario() -> None:
        backend = _PinnedNetworkBackend(target)
        stream = await backend.connect_tcp("example.com", 443)
        assert stream is delegate.stream
        assert delegate.hosts == [PUBLIC_IPV4]

        with pytest.raises(DomainError) as captured:
            await backend.connect_tcp("attacker.example", 443)
        assert captured.value.code is ErrorCode.SSRF_BLOCKED

    asyncio.run(scenario())
