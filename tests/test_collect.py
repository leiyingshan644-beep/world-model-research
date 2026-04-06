from unittest.mock import patch, MagicMock


def test_fiblabs_parses_arxiv_links():
    from collect import fetch_from_fiblabs
    fake_readme = """
## Papers
| [DreamerV3](https://arxiv.org/abs/2301.04589) | NeurIPS 2023 |
| [TD-MPC2](https://arxiv.org/abs/2310.16828) | ICLR 2024 |
"""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = fake_readme
    with patch("requests.get", return_value=mock_resp):
        papers = fetch_from_fiblabs()
    assert len(papers) == 2
    ids = {p["arxiv_id"] for p in papers}
    assert "2301.04589" in ids
    assert "2310.16828" in ids


def test_fiblabs_handles_network_error():
    from collect import fetch_from_fiblabs
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404
    with patch("requests.get", return_value=mock_resp):
        papers = fetch_from_fiblabs()
    assert papers == []


def test_collect_deduplicates_by_id(tmp_path, monkeypatch):
    import utils.db as db_module
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    fake_paper = {
        "id": "2301.04589", "title": "DreamerV3", "authors": [],
        "year": 2023, "venue": "neurips", "abstract": "world model",
        "arxiv_id": "2301.04589", "pdf_url": None,
    }

    with patch("collect.fetch_from_fiblabs", return_value=[fake_paper, fake_paper]):
        with patch("collect.fetch_from_s2", return_value=[]):
            from collect import collect
            collect()

    papers = db_module.get_papers()
    assert len(papers) == 1
