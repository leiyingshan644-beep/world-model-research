import json
import os
import tempfile
from unittest.mock import patch, MagicMock


def test_returns_no_pdf_when_path_missing():
    from summarize import summarize_paper
    paper = {"id": "x", "pdf_path": "/nonexistent/path.pdf"}
    summary, status = summarize_paper(paper)
    assert status == "no_pdf"
    assert summary is None


def test_returns_no_pdf_when_path_is_none():
    from summarize import summarize_paper
    paper = {"id": "x", "pdf_path": None}
    summary, status = summarize_paper(paper)
    assert status == "no_pdf"
    assert summary is None


def test_returns_structured_summary():
    from summarize import summarize_paper
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf content")
        pdf_path = f.name
    try:
        paper = {"id": "2301.04589", "pdf_path": pdf_path}
        fake_json = json.dumps({
            "problem":    "World models lack long-horizon consistency.",
            "innovation": "New latent recurrent architecture.",
            "method":     "RSSM with discrete latents.",
            "results":    "SOTA on Atari and DM Control.",
            "gaps":       "Slow training; limited 3D understanding.",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value \
            .choices[0].message.content = fake_json
        with patch("summarize.extract_text", return_value="some paper text"):
            with patch("summarize.OpenAI", return_value=mock_client):
                summary, status = summarize_paper(paper)
        assert status == "ok"
        assert summary["paper_id"] == "2301.04589"
        assert summary["problem"] == "World models lack long-horizon consistency."
        assert "model_used" in summary
        assert "created_at" in summary
    finally:
        os.unlink(pdf_path)


def test_strips_markdown_fences_from_llm_output():
    from summarize import summarize_paper
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake")
        pdf_path = f.name
    try:
        paper = {"id": "abc", "pdf_path": pdf_path}
        fake_json = json.dumps({"problem": "P", "innovation": "I",
                                "method": "M", "results": "R", "gaps": "G"})
        wrapped = f"```json\n{fake_json}\n```"
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value \
            .choices[0].message.content = wrapped
        with patch("summarize.extract_text", return_value="text"):
            with patch("summarize.OpenAI", return_value=mock_client):
                summary, status = summarize_paper(paper)
        assert status == "ok"
        assert summary["problem"] == "P"
    finally:
        os.unlink(pdf_path)
