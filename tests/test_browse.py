import pytest
from unittest.mock import patch


@pytest.fixture
def client():
    from browse import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _paper(**kwargs):
    base = {
        "id": "2301.04589", "title": "DreamerV3", "venue": "neurips",
        "year": 2023, "relevance_label": "high", "status": "summarized",
        "relevance_score": 0.85, "abstract": "A world model paper.",
        "pdf_path": "/tmp/fake.pdf",
    }
    base.update(kwargs)
    return base


def test_index_returns_200(client):
    with patch("browse.get_papers", return_value=[]):
        resp = client.get("/")
    assert resp.status_code == 200


def test_index_shows_paper_title(client):
    with patch("browse.get_papers", return_value=[_paper()]):
        resp = client.get("/")
    assert b"DreamerV3" in resp.data


def test_index_search_calls_search_papers(client):
    with patch("browse.search_papers", return_value=[]) as mock_search:
        client.get("/?q=dreamer")
    mock_search.assert_called_once_with("dreamer")


def test_paper_detail_200(client):
    paper = _paper()
    summary = {
        "paper_id": "2301.04589", "problem": "P", "innovation": "I",
        "method": "M", "results": "R", "gaps": "G", "my_thoughts": "",
    }
    with patch("browse.get_papers", return_value=[paper]):
        with patch("browse.get_summary", return_value=summary):
            resp = client.get("/paper/2301.04589")
    assert resp.status_code == 200
    assert b"DreamerV3" in resp.data
    assert b"Innovation" in resp.data


def test_paper_detail_404_for_unknown(client):
    with patch("browse.get_papers", return_value=[]):
        resp = client.get("/paper/nonexistent-id")
    assert resp.status_code == 404


def test_save_thoughts_updates_db(client):
    with patch("browse.update_my_thoughts") as mock_update:
        resp = client.post(
            "/save_thoughts/2301.04589",
            json={"thoughts": "very promising direction"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    mock_update.assert_called_once_with("2301.04589", "very promising direction")
