from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# fetch_from_openalex
# ---------------------------------------------------------------------------

def test_openalex_returns_empty_on_http_error():
    from collect import fetch_from_openalex
    with patch("collect.requests.get") as mock_get:
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 500
        result = fetch_from_openalex(["neurips"], (2023, 2023))
    assert result == []


def test_openalex_filters_to_target_venues():
    from collect import fetch_from_openalex
    works = [
        {
            "id": "https://openalex.org/W1",
            "title": "DreamerV3: World Model for RL",
            "abstract_inverted_index": {"world": [0], "model": [1]},
            "publication_year": 2023,
            "authorships": [{"author": {"display_name": "Author A"}}],
            "primary_location": {
                "source": {"display_name": "Neural Information Processing Systems"},
                "pdf_url": None,
            },
            "ids": {"arxiv": "https://arxiv.org/abs/2301.04589", "doi": None},
        },
        {
            "id": "https://openalex.org/W2",
            "title": "Some Unrelated Paper",
            "abstract_inverted_index": {},
            "publication_year": 2023,
            "authorships": [],
            "primary_location": {
                "source": {"display_name": "Some Workshop"},
                "pdf_url": None,
            },
            "ids": {},
        },
    ]
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = {
        "results": works,
        "meta": {"count": 2, "next_cursor": None},
    }
    with patch("collect.requests.get", return_value=resp):
        result = fetch_from_openalex(["neurips"], (2023, 2023))

    assert len(result) == 1
    assert result[0]["venue"] == "neurips"
    assert result[0]["arxiv_id"] == "2301.04589"
    assert result[0]["source"] == "openalex"


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
      <dt class="ptitle"><a href="/content/cvpr2023/foo">World Model for Vision</a></dt>
      <dd><a href="/content/cvpr2023/foo/foo.pdf">pdf</a></dd>
      <dt class="ptitle"><a href="/content/cvpr2023/bar">Generic Segmentation</a></dt>
      <dd><a href="/content/cvpr2023/bar/bar.pdf">pdf</a></dd>
    </dl></body></html>"""
    resp = MagicMock()
    resp.ok = True
    resp.text = html
    with patch("collect.requests.get", return_value=resp):
        result = fetch_from_cvf(2023)
    assert len(result) == 1
    assert result[0]["venue"] == "cvpr"
    assert result[0]["source"] == "cvf"


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
    resp = MagicMock()
    resp.ok = True
    resp.text = fake_readme
    with patch("collect.requests.get", return_value=resp):
        papers = fetch_from_fiblabs()
    assert len(papers) == 2
    assert {p["arxiv_id"] for p in papers} == {"2301.04589", "2310.16828"}
    assert all(p["source"] == "fiblabs" for p in papers)


def test_fiblabs_returns_empty_on_error():
    from collect import fetch_from_fiblabs
    with patch("collect.requests.get") as mock_get:
        mock_get.return_value.ok = False
        mock_get.return_value.status_code = 404
        result = fetch_from_fiblabs()
    assert result == []


# ---------------------------------------------------------------------------
# crossref_via_openalex
# ---------------------------------------------------------------------------

def test_crossref_updates_venue_for_unknown_papers(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()

    # Insert an arXiv paper with no venue
    paper = {
        "id": "2301.04589", "title": "World model paper", "authors": [],
        "year": 2023, "venue": None, "source": "arxiv", "doi": "",
        "abstract": "world model", "arxiv_id": "2301.04589",
        "pdf_url": "https://arxiv.org/pdf/2301.04589",
    }
    db_module.upsert_paper(paper)

    oa_resp = MagicMock()
    oa_resp.ok = True
    oa_resp.json.return_value = {
        "results": [{
            "ids": {
                "arxiv": "https://arxiv.org/abs/2301.04589",
                "doi":   "https://doi.org/10.0/test",
            },
            "primary_location": {
                "source": {"display_name": "Neural Information Processing Systems"}
            },
            "publication_year": 2023,
        }]
    }

    papers_dict = {"2301.04589": paper}
    with patch("collect.requests.get", return_value=oa_resp):
        from collect import crossref_via_openalex
        updated = crossref_via_openalex(papers_dict)

    assert updated == 1
    stored = db_module.get_papers()
    assert stored[0]["venue"] == "neurips"
    assert stored[0]["doi"] == "10.0/test"


# ---------------------------------------------------------------------------
# collect()
# ---------------------------------------------------------------------------

def test_collect_deduplicates_and_writes_to_db(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()

    fake = {
        "id": "2301.04589", "title": "DreamerV3 world model", "authors": [],
        "year": 2023, "venue": "neurips", "source": "openalex", "doi": "",
        "abstract": "world model paper.", "arxiv_id": "2301.04589", "pdf_url": None,
    }

    with patch("collect.fetch_from_openalex",  return_value=[fake]):
        with patch("collect.fetch_from_cvf",        return_value=[fake]):
            with patch("collect.fetch_from_arxiv",  return_value=[fake]):
                with patch("collect.fetch_from_fiblabs", return_value=[fake]):
                    with patch("collect.crossref_via_openalex", return_value=0):
                        from collect import collect
                        collect()

    papers = db_module.get_papers()
    assert len(papers) == 1
    assert papers[0]["id"] == "2301.04589"
    assert papers[0]["source"] == "openalex"


# ---------------------------------------------------------------------------
# collect_single / _parse_arxiv_id
# ---------------------------------------------------------------------------

def test_parse_arxiv_id_from_full_url():
    from collect import _parse_arxiv_id
    assert _parse_arxiv_id("https://arxiv.org/abs/2506.21976") == "2506.21976"

def test_parse_arxiv_id_from_bare_id():
    from collect import _parse_arxiv_id
    assert _parse_arxiv_id("2506.21976") == "2506.21976"

def test_parse_arxiv_id_with_prefix():
    from collect import _parse_arxiv_id
    assert _parse_arxiv_id("arxiv:2506.21976") == "2506.21976"

def test_parse_arxiv_id_invalid():
    from collect import _parse_arxiv_id
    assert _parse_arxiv_id("https://example.com/no-id") is None

def test_collect_single_adds_paper_to_db(tmp_path, monkeypatch):
    import datetime, utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()

    fake_result = MagicMock()
    fake_result.entry_id     = "https://arxiv.org/abs/2506.21976v1"
    fake_result.title        = "HunyuanWorld Test Paper"
    author_mock = MagicMock()
    author_mock.name = "Author A"
    fake_result.authors      = [author_mock]
    fake_result.published    = MagicMock(year=2025)
    fake_result.summary      = "A world model paper abstract."
    fake_result.comment      = "NeurIPS 2025"
    fake_result.journal_ref  = ""

    with patch("collect.arxiv_pkg.Client") as mock_client_cls:
        mock_client_cls.return_value.results.return_value = iter([fake_result])
        with patch("collect.crossref_via_openalex", return_value=0):
            from collect import collect_single
            collect_single("https://arxiv.org/abs/2506.21976")

    papers = db_module.get_papers()
    assert len(papers) == 1
    assert papers[0]["id"] == "2506.21976"
    assert papers[0]["source"] == "arxiv_manual"
    assert papers[0]["venue"] == "neurips"
