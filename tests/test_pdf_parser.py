import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


def test_extract_returns_string():
    from utils.pdf_parser import extract_text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hello world model paper."
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text("/fake/path.pdf")
    assert "Hello world model paper." in result


def test_extract_respects_max_chars():
    from utils.pdf_parser import extract_text
    long_text = "A" * 20000
    mock_page = MagicMock()
    mock_page.extract_text.return_value = long_text
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text("/fake/path.pdf", max_chars=100)
    assert len(result) == 100


def test_extract_handles_none_page_text():
    from utils.pdf_parser import extract_text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = None
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text("/fake/path.pdf")
    assert result == ""
