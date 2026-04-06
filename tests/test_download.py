import os
import tempfile
from unittest.mock import patch, MagicMock


def test_skips_existing_file():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = os.path.join(tmpdir, "neurips", "2023", "test123.pdf")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").close()
        paper = {"id": "test123", "arxiv_id": "test123",
                 "pdf_url": None, "venue": "neurips", "year": 2023}
        _, status = download_pdf(paper, tmpdir)
        assert status == "exists"


def test_returns_no_url_when_no_links():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        paper = {"id": "s2:abc", "arxiv_id": None,
                 "pdf_url": None, "venue": "icml", "year": 2023}
        _, status = download_pdf(paper, tmpdir)
        assert status == "no_url"


def test_downloads_successfully():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        paper = {"id": "2301.00001", "arxiv_id": "2301.00001",
                 "pdf_url": None, "venue": "neurips", "year": 2023}
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.iter_content = lambda chunk_size: [b"%PDF-1.4 fake"]
        with patch("requests.get", return_value=mock_resp):
            path, status = download_pdf(paper, tmpdir)
        assert status == "downloaded"
        assert os.path.exists(path)


def test_falls_back_to_pdf_url():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        paper = {"id": "s2:xyz", "arxiv_id": None,
                 "pdf_url": "https://example.com/paper.pdf",
                 "venue": "cvpr", "year": 2022}
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.iter_content = lambda chunk_size: [b"%PDF-1.4 fake"]
        with patch("requests.get", return_value=mock_resp):
            path, status = download_pdf(paper, tmpdir)
        assert status == "downloaded"
