"""Tests for ai_sdlc_claudecode.extract — unified JSON extraction."""

import json
import tempfile
from pathlib import Path

import pytest

from ai_sdlc_claudecode.extract import extract_and_save, extract_json


class TestExtractJsonLevel1:
    """Level 1: Direct json.loads on entire text."""

    def test_pure_json(self) -> None:
        text = '{"stage_id": "S3", "status": "passed"}'
        assert extract_json(text) == {"stage_id": "S3", "status": "passed"}

    def test_pure_json_with_whitespace(self) -> None:
        text = '  \n  {"key": "value"}  \n  '
        assert extract_json(text) == {"key": "value"}

    def test_empty_string(self) -> None:
        assert extract_json("") is None

    def test_none_like_empty(self) -> None:
        assert extract_json("   ") is None

    def test_returns_none_for_list(self) -> None:
        """extract_json returns dicts only, not lists."""
        assert extract_json('[1, 2, 3]') is None


class TestExtractJsonLevel2:
    """Level 2: Markdown ```json ... ``` blocks."""

    def test_markdown_wrapped(self) -> None:
        text = 'Here is the output:\n```json\n{"stage_id": "S1"}\n```\nDone.'
        assert extract_json(text) == {"stage_id": "S1"}

    def test_multiple_blocks_takes_last(self) -> None:
        text = (
            '```json\n{"stage_id": "S1"}\n```\n'
            'Some text\n'
            '```json\n{"stage_id": "S2"}\n```'
        )
        assert extract_json(text) == {"stage_id": "S2"}

    def test_markdown_with_extra_text(self) -> None:
        text = (
            "I've analyzed the requirements and here's my output:\n\n"
            "```json\n"
            '{\n  "stage_id": "S1",\n  "features": ["auth", "api"]\n}\n'
            "```\n\n"
            "Let me know if you need changes."
        )
        result = extract_json(text)
        assert result is not None
        assert result["stage_id"] == "S1"
        assert result["features"] == ["auth", "api"]


class TestExtractJsonLevel3:
    """Level 3: Brace-balanced extraction."""

    def test_nested_objects(self) -> None:
        text = (
            'The API design:\n'
            '{"api_contracts": [{"endpoint": "/users", "method": "GET"}], "stage_id": "S2"}'
        )
        result = extract_json(text)
        assert result is not None
        assert result["stage_id"] == "S2"
        assert len(result["api_contracts"]) == 1

    def test_deeply_nested(self) -> None:
        text = 'Output: {"a": {"b": {"c": {"d": 1}}}}'
        result = extract_json(text)
        assert result == {"a": {"b": {"c": {"d": 1}}}}

    def test_json_with_strings_containing_braces(self) -> None:
        text = 'Result: {"code": "if (x) { return y; }", "lang": "java"}'
        result = extract_json(text)
        assert result is not None
        assert result["lang"] == "java"
        assert "{" in result["code"]

    def test_multiple_json_objects_takes_last(self) -> None:
        text = '{"old": true} some text {"new": true}'
        result = extract_json(text)
        assert result == {"new": True}


class TestExtractJsonLevel4:
    """Level 4: JSON repair."""

    def test_trailing_comma_object(self) -> None:
        text = '{"stage_id": "S3", "status": "passed",}'
        result = extract_json(text)
        assert result is not None
        assert result["stage_id"] == "S3"

    def test_trailing_comma_array(self) -> None:
        text = '{"items": [1, 2, 3,]}'
        result = extract_json(text)
        assert result is not None
        assert result["items"] == [1, 2, 3]

    def test_bom_character(self) -> None:
        text = '\ufeff{"stage_id": "S1"}'
        result = extract_json(text)
        assert result == {"stage_id": "S1"}

    def test_javascript_comments(self) -> None:
        text = (
            '```json\n'
            '{\n'
            '  // This is the stage ID\n'
            '  "stage_id": "S3"\n'
            '}\n'
            '```'
        )
        result = extract_json(text)
        assert result is not None
        assert result["stage_id"] == "S3"

    def test_no_json_at_all(self) -> None:
        text = "This is just regular text with no JSON whatsoever."
        assert extract_json(text) is None

    def test_malformed_beyond_repair(self) -> None:
        text = "{stage_id: S3, status: passed}"  # unquoted keys and values
        # This may or may not parse depending on repair; the key thing is no crash
        result = extract_json(text)
        # If it returns None, that's acceptable for this level of damage
        assert result is None or isinstance(result, dict)


class TestExtractAndSave:
    """Test extract_and_save file I/O."""

    def test_save_from_text(self, tmp_path: Path) -> None:
        output = tmp_path / "output.json"
        ok = extract_and_save(str(output), text='{"stage_id": "S1"}')
        assert ok is True
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["stage_id"] == "S1"

    def test_save_from_file(self, tmp_path: Path) -> None:
        input_file = tmp_path / "raw.txt"
        input_file.write_text('Some preamble\n```json\n{"ok": true}\n```\n')
        output = tmp_path / "sub" / "output.json"

        ok = extract_and_save(str(output), input_path=str(input_file))
        assert ok is True
        assert json.loads(output.read_text()) == {"ok": True}

    def test_save_failure_returns_false(self, tmp_path: Path) -> None:
        output = tmp_path / "output.json"
        ok = extract_and_save(str(output), text="no json here")
        assert ok is False
        assert not output.exists()

    def test_raises_without_input(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Either input_path or text"):
            extract_and_save(str(tmp_path / "out.json"))

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        output = tmp_path / "deep" / "nested" / "output.json"
        ok = extract_and_save(str(output), text='{"x": 1}')
        assert ok is True
        assert output.exists()
