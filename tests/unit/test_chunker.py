from knowledge_agents.adapters.chunker import ChunkerConfig, MarkdownChunker


def test_headings_start_new_chunks_and_preserve_heading_paths() -> None:
    chunker = MarkdownChunker(ChunkerConfig(target_tokens=20, max_tokens=30, overlap_tokens=2))
    content = """# Alpha

First paragraph with durable context.

## Beta

Second paragraph with more context.
"""

    chunks = chunker.chunk(document_id="doc-1", content=content, source_locator="note.md")

    assert len(chunks) == 2
    assert chunks[0].heading_path == ("Alpha",)
    assert chunks[1].heading_path == ("Alpha", "Beta")
    assert chunks[0].source_locator == "note.md#L1-L3"
    assert chunks[1].source_locator == "note.md#L5-L7"


def test_lists_tables_and_code_blocks_remain_indivisible_when_they_fit() -> None:
    chunker = MarkdownChunker(ChunkerConfig(target_tokens=5, max_tokens=30, overlap_tokens=0))
    content = """# Structures

- first list item
- second list item

| Name | Value |
| --- | --- |
| alpha | one |
| beta | two |

```python
value = {"key": "content"}
print(value)
```
"""

    chunks = chunker.chunk(document_id="doc-2", content=content, source_locator="structures.md")

    rendered = tuple(chunk.content for chunk in chunks)
    assert any("- first list item\n- second list item" in content for content in rendered)
    assert any("| Name | Value |\n| --- | --- |" in content for content in rendered)
    assert any(
        '```python\nvalue = {"key": "content"}\nprint(value)\n```' in content
        for content in rendered
    )


def test_overlap_applies_only_to_adjacent_chunks_and_respects_maximum() -> None:
    chunker = MarkdownChunker(ChunkerConfig(target_tokens=6, max_tokens=8, overlap_tokens=2))
    content = "one two three four five six\n\nseven eight nine ten eleven twelve"

    chunks = chunker.chunk(document_id="doc-3", content=content, source_locator="overlap.md")

    assert len(chunks) == 2
    assert chunks[1].content.startswith("five six\n\nseven")
    assert all(chunk.token_count <= 8 for chunk in chunks)
    assert chunks[0].content_hash != chunks[1].content_hash


def test_oversized_structure_is_split_at_the_hard_limit() -> None:
    chunker = MarkdownChunker(ChunkerConfig(target_tokens=4, max_tokens=6, overlap_tokens=0))
    content = "- " + " ".join(f"token-{index}" for index in range(14))

    chunks = chunker.chunk(document_id="doc-4", content=content, source_locator="large.md")

    assert len(chunks) == 3
    assert all(chunk.token_count <= 6 for chunk in chunks)
