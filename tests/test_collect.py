from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# fetch_from_openreview
# ---------------------------------------------------------------------------

def test_openreview_returns_empty_on_http_error():
    from collect import fetch_from_openreview
    with patch("collect.requests.get") as mock_get:
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 500
        result = fetch_from_openreview("neurips", 2023)
    assert result == []


def test_openreview_filters_by_keyword():
    from collect import fetch_from_openreview
    notes = [
        {
            "id": "note1",
            "content": {
                "title":    {"value": "DreamerV3: World Model for RL"},
                "abstract": {"value": "A generative world model approach."},
                "authors":  {"value": ["Author A"]},
                "pdf":      {"value": "/pdf/note1.pdf"},
            },
        },
        {
            "id": "note2",
            "content": {
                "title":    {"value": "Unrelated Vision Paper"},
                "abstract": {"value": "Nothing relevant here."},
                "authors":  {"value": ["Author B"]},
                "pdf":      {"value": "/pdf/note2.pdf"},
            },
        },
    ]
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"notes": notes}

    with patch("collect.requests.get", return_value=response):
        result = fetch_from_openreview("neurips", 2023)

    assert len(result) == 1
    assert "DreamerV3" in result[0]["title"]
    assert result[0]["venue"] == "neurips"
    assert result[0]["year"] == 2023


# ---------------------------------------------------------------------------
# fetch_from_cvf
# ---------------------------------------------------------------------------

def test_cvf_returns_empty_on_http_error():
    from collect import fetch_from_cvf
    with patch("collect.requests.get") as mock_get:
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 404
        result = fetch_from_cvf(2023)
    assert result == []


def test_cvf_parses_matching_titles():
    from collect import fetch_from_cvf
    html = """<html><body><dl>
      <dt class="ptitle"><a href="/content/cvpr2023/foo">World Model for Vision Tasks</a></dt>
      <dd><a href="/content/cvpr2023/foo/foo.pdf">pdf</a></dd>
      <dt class="ptitle"><a href="/content/cvpr2023/bar">Generic Image Segmentation</a></dt>
      <dd><a href="/content/cvpr2023/bar/bar.pdf">pdf</a></dd>
    </dl></body></html>"""
    response = MagicMock()
    response.ok = True
    response.text = html

    with patch("collect.requests.get", return_value=response):
        result = fetch_from_cvf(2023)

    assert len(result) == 1
    assert "World Model" in result[0]["title"]
    assert result[0]["venue"] == "cvpr"


# ---------------------------------------------------------------------------
# fetch_from_fiblabs
# ---------------------------------------------------------------------------

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
    with patch("collect.requests.get", return_value=mock_resp):
        papers = fetch_from_fiblabs()
    assert len(papers) == 2
    ids = {p["arxiv_id"] for p in papers}
    assert "2301.04589" in ids
    assert "2310.16828" in ids


def test_fiblabs_returns_empty_on_error():
    from collect import fetch_from_fiblabs
    with patch("collect.requests.get") as mock_get:
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 404
        result = fetch_from_fiblabs()
    assert result == []


# ---------------------------------------------------------------------------
# collect()
# ---------------------------------------------------------------------------

def test_collect_deduplicates_and_writes_to_db(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()

    fake_paper = {
        "id": "2301.04589", "title": "DreamerV3 world model", "authors": [],
        "year": 2023, "venue": "neurips", "abstract": "world model paper.",
        "arxiv_id": "2301.04589", "pdf_url": None,
    }

    with patch("collect.fetch_from_openreview", return_value=[fake_paper]):
        with patch("collect.fetch_from_cvf",        return_value=[fake_paper]):
            with patch("collect.fetch_from_arxiv",  return_value=[fake_paper]):
                with patch("collect.fetch_from_fiblabs", return_value=[fake_paper]):
                    from collect import collect
                    collect()

    papers = db_module.get_papers()
    assert len(papers) == 1
    assert papers[0]["id"] == "2301.04589"
