import json
from collections.abc import Iterator

from app.stream_parser import parse_stream


class FakeResponse:
    """Minimal stand-in for requests.Response that supports iter_lines()."""

    def __init__(self, lines: list[str | bytes]):
        self._lines = lines

    def iter_lines(self) -> Iterator[str | bytes]:
        yield from self._lines


def test_parse_stream_skips_non_object_and_malformed_frames():
    """Non-object JSON and malformed lines must not abort the stream; valid events still emit."""
    lines = [
        b"",
        "null",
        "[]",
        "42",
        '"just a string"',
        "true",
        "{not valid json",
        json.dumps({"type": "markdown-chat", "value": "Hello from markdown"}),
        json.dumps({
            "type": "patch",
            "v": [
                {
                    "o": "a",
                    "path": "/s/-",
                    "v": {"type": "text", "value": [{"type": "text", "content": "patch text"}]}
                }
            ]
        }),
    ]

    response = FakeResponse(lines)
    events = list(parse_stream(response))

    # At least the markdown-chat final_content should appear
    final_contents = [e for e in events if e.get("type") == "final_content"]
    assert any("Hello from markdown" in e.get("text", "") for e in final_contents)

    # The later patch event must also survive the invalid frames.
    assert {"type": "content", "text": "patch text"} in events


def test_parse_stream_handles_bytes_and_str_lines():
    """Both bytes and str lines from iter_lines are accepted."""
    good_event = json.dumps({"type": "markdown-chat", "value": "bytes or str"})
    lines = [
        good_event.encode("utf-8"),
        good_event,  # str
        b"null",
        "[]",
    ]
    response = FakeResponse(lines)
    events = list(parse_stream(response))
    assert any(e.get("type") == "final_content" and "bytes or str" in e.get("text", "") for e in events)
