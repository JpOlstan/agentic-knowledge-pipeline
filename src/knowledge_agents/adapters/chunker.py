from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

TOKEN_PATTERN = re.compile(r"\S+")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_PATTERN = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass(frozen=True, slots=True)
class ChunkerConfig:
    target_tokens: int = 800
    max_tokens: int = 1_200
    overlap_tokens: int = 120
    version: str = "v1"

    def __post_init__(self) -> None:
        if self.target_tokens <= 0:
            raise ValueError("target_tokens must be positive")
        if self.max_tokens < self.target_tokens:
            raise ValueError("max_tokens must be greater than or equal to target_tokens")
        if not 0 <= self.overlap_tokens < self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")


@dataclass(frozen=True, slots=True)
class MarkdownChunk:
    document_id: str
    ordinal: int
    content: str
    content_hash: str
    heading_path: tuple[str, ...]
    source_locator: str
    token_count: int


@dataclass(frozen=True, slots=True)
class _Block:
    content: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    kind: str


class MarkdownChunker:
    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()

    def chunk(
        self,
        *,
        document_id: str,
        content: str,
        source_locator: str,
    ) -> tuple[MarkdownChunk, ...]:
        blocks = _markdown_blocks(content)
        if not blocks:
            return ()

        groups: list[list[_Block]] = []
        current: list[_Block] = []
        current_tokens = 0
        for block in _split_oversized_blocks(blocks, self.config.max_tokens):
            block_tokens = _token_count(block.content)
            starts_section = block.kind == "heading" and current
            exceeds_target = current and current_tokens + block_tokens > self.config.target_tokens
            exceeds_max = current_tokens + block_tokens > self.config.max_tokens
            if starts_section or exceeds_target or exceeds_max:
                groups.append(current)
                current = []
                current_tokens = 0
            current.append(block)
            current_tokens += block_tokens
        if current:
            groups.append(current)

        chunks: list[MarkdownChunk] = []
        previous_content = ""
        for ordinal, group in enumerate(groups):
            body = "\n\n".join(block.content.strip() for block in group if block.content.strip())
            if ordinal and self.config.overlap_tokens:
                overlap = _tail_tokens(previous_content, self.config.overlap_tokens)
                available = self.config.max_tokens - _token_count(body)
                if overlap and available > 0:
                    overlap = _tail_tokens(overlap, min(self.config.overlap_tokens, available))
                    body = f"{overlap}\n\n{body}"
            chunks.append(
                MarkdownChunk(
                    document_id=document_id,
                    ordinal=ordinal,
                    content=body,
                    content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    heading_path=group[0].heading_path,
                    source_locator=_locator(
                        source_locator, group[0].start_line, group[-1].end_line
                    ),
                    token_count=_token_count(body),
                )
            )
            previous_content = body
        return tuple(chunks)


def _markdown_blocks(content: str) -> tuple[_Block, ...]:
    lines = content.splitlines()
    blocks: list[_Block] = []
    headings: list[str] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue

        start = index
        heading = HEADING_PATTERN.match(lines[index])
        if heading:
            level = len(heading.group(1))
            headings = headings[: level - 1]
            headings.append(heading.group(2).strip())
            blocks.append(_Block(lines[index], tuple(headings), start + 1, start + 1, "heading"))
            index += 1
            continue

        fence = FENCE_PATTERN.match(lines[index])
        if fence:
            marker = fence.group(1)
            index += 1
            while index < len(lines):
                if lines[index].lstrip().startswith(marker):
                    index += 1
                    break
                index += 1
            blocks.append(
                _Block("\n".join(lines[start:index]), tuple(headings), start + 1, index, "code")
            )
            continue

        if _is_table_start(lines, index):
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                index += 1
            blocks.append(
                _Block("\n".join(lines[start:index]), tuple(headings), start + 1, index, "table")
            )
            continue

        if LIST_PATTERN.match(lines[index]):
            index += 1
            while index < len(lines):
                line = lines[index]
                if not line.strip():
                    break
                if HEADING_PATTERN.match(line) or FENCE_PATTERN.match(line):
                    break
                if LIST_PATTERN.match(line) or line.startswith((" ", "\t")):
                    index += 1
                    continue
                break
            blocks.append(
                _Block("\n".join(lines[start:index]), tuple(headings), start + 1, index, "list")
            )
            continue

        index += 1
        while index < len(lines):
            if not lines[index].strip() or _starts_special_block(lines, index):
                break
            index += 1
        blocks.append(
            _Block("\n".join(lines[start:index]), tuple(headings), start + 1, index, "paragraph")
        )
    return tuple(blocks)


def _split_oversized_blocks(blocks: tuple[_Block, ...], maximum: int) -> tuple[_Block, ...]:
    split: list[_Block] = []
    for block in blocks:
        tokens = TOKEN_PATTERN.findall(block.content)
        if len(tokens) <= maximum:
            split.append(block)
            continue
        for offset in range(0, len(tokens), maximum):
            split.append(
                _Block(
                    content=" ".join(tokens[offset : offset + maximum]),
                    heading_path=block.heading_path,
                    start_line=block.start_line,
                    end_line=block.end_line,
                    kind=block.kind,
                )
            )
    return tuple(split)


def _starts_special_block(lines: list[str], index: int) -> bool:
    return bool(
        HEADING_PATTERN.match(lines[index])
        or FENCE_PATTERN.match(lines[index])
        or LIST_PATTERN.match(lines[index])
        or _is_table_start(lines, index)
    )


def _is_table_start(lines: list[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and "|" in lines[index]
        and TABLE_SEPARATOR_PATTERN.match(lines[index + 1]) is not None
    )


def _token_count(content: str) -> int:
    return len(TOKEN_PATTERN.findall(content))


def _tail_tokens(content: str, limit: int) -> str:
    return " ".join(TOKEN_PATTERN.findall(content)[-limit:])


def _locator(source: str, start_line: int, end_line: int) -> str:
    return f"{source}#L{start_line}-L{end_line}"
