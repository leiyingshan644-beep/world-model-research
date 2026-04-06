import os
import tempfile
import pytest

_TEMP_DB = tempfile.mktemp(suffix=".db")

@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", _TEMP_DB)
    db_module.init_db()
    yield
    if os.path.exists(_TEMP_DB):
        os.remove(_TEMP_DB)

def _paper(id="p1", venue="neurips", year=2023, label=None):
    return {
        "id": id, "title": f"Title {id}", "authors": ["Alice"],
        "year": year, "venue": venue,
        "abstract": "A world model paper.", "arxiv_id": id, "pdf_url": None,
    }

def test_upsert_and_get():
    from utils.db import upsert_paper, get_papers
    upsert_paper(_paper())
    papers = get_papers()
    assert len(papers) == 1
    assert papers[0]["title"] == "Title p1"

def test_upsert_is_idempotent():
    from utils.db import upsert_paper, get_papers
    upsert_paper(_paper())
    upsert_paper(_paper())
    assert len(get_papers()) == 1

def test_filter_by_venue():
    from utils.db import upsert_paper, get_papers
    upsert_paper(_paper("a", venue="neurips"))
    upsert_paper(_paper("b", venue="icml"))
    assert len(get_papers(venue="neurips")) == 1

def test_filter_by_label():
    from utils.db import upsert_paper, update_paper, get_papers
    upsert_paper(_paper("a"))
    update_paper("a", relevance_label="high")
    assert len(get_papers(label="high")) == 1
    assert len(get_papers(label="mid")) == 0

def test_update_paper():
    from utils.db import upsert_paper, update_paper, get_papers
    upsert_paper(_paper())
    update_paper("p1", relevance_score=0.9, status="downloaded")
    p = get_papers()[0]
    assert p["relevance_score"] == 0.9
    assert p["status"] == "downloaded"

def test_summary_roundtrip():
    from utils.db import upsert_paper, upsert_summary, get_summary
    upsert_paper(_paper())
    upsert_summary({
        "paper_id": "p1", "problem": "P", "innovation": "I",
        "method": "M", "results": "R", "gaps": "G",
        "model_used": "deepseek-chat", "created_at": "2026-01-01T00:00:00",
    })
    s = get_summary("p1")
    assert s["problem"] == "P"
    assert s["my_thoughts"] == ""

def test_update_my_thoughts():
    from utils.db import upsert_paper, upsert_summary, update_my_thoughts, get_summary
    upsert_paper(_paper())
    upsert_summary({"paper_id": "p1", "problem": "", "innovation": "",
                    "method": "", "results": "", "gaps": "",
                    "model_used": "m", "created_at": "2026-01-01T00:00:00"})
    update_my_thoughts("p1", "very interesting!")
    assert get_summary("p1")["my_thoughts"] == "very interesting!"

def test_search_papers():
    from utils.db import upsert_paper, search_papers
    upsert_paper({"id": "z", "title": "DreamerV3 World Model", "authors": [],
                  "year": 2024, "venue": "iclr",
                  "abstract": "latent world model for RL", "arxiv_id": "z", "pdf_url": None})
    assert len(search_papers("dreamer")) == 1
    assert len(search_papers("transformer")) == 0

def test_upsert_summary_preserves_my_thoughts():
    from utils.db import upsert_paper, upsert_summary, update_my_thoughts, get_summary
    upsert_paper(_paper())
    upsert_summary({"paper_id": "p1", "problem": "P", "innovation": "I",
                    "method": "M", "results": "R", "gaps": "G",
                    "model_used": "m", "created_at": "2026-01-01T00:00:00"})
    update_my_thoughts("p1", "important insight!")
    # Re-run summarize — should NOT erase my_thoughts
    upsert_summary({"paper_id": "p1", "problem": "P2", "innovation": "I2",
                    "method": "M2", "results": "R2", "gaps": "G2",
                    "model_used": "m2", "created_at": "2026-01-02T00:00:00"})
    s = get_summary("p1")
    assert s["my_thoughts"] == "important insight!"
    assert s["problem"] == "P2"  # AI content updated


def test_add_and_get_tags(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    paper = {"id": "abc", "title": "T", "authors": [], "year": 2023,
             "venue": "neurips", "source": "", "doi": "", "abstract": "",
             "arxiv_id": "abc", "pdf_url": None}
    db_module.upsert_paper(paper)
    db_module.add_tag_to_paper("abc", "embodied")
    db_module.add_tag_to_paper("abc", "planning")
    tags = db_module.get_tags_for_paper("abc")
    assert set(tags) == {"embodied", "planning"}

def test_remove_tag(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    paper = {"id": "abc", "title": "T", "authors": [], "year": 2023,
             "venue": "neurips", "source": "", "doi": "", "abstract": "",
             "arxiv_id": "abc", "pdf_url": None}
    db_module.upsert_paper(paper)
    db_module.add_tag_to_paper("abc", "embodied")
    db_module.remove_tag_from_paper("abc", "embodied")
    assert db_module.get_tags_for_paper("abc") == []

def test_get_all_tags(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    for pid, tag in [("a", "planning"), ("b", "planning"), ("c", "embodied")]:
        p = {"id": pid, "title": "T", "authors": [], "year": 2023,
             "venue": "neurips", "source": "", "doi": "", "abstract": "",
             "arxiv_id": pid, "pdf_url": None}
        db_module.upsert_paper(p)
        db_module.add_tag_to_paper(pid, tag)
    all_tags = db_module.get_all_tags()
    names = [t["name"] for t in all_tags]
    assert "planning" in names and "embodied" in names
    planning = next(t for t in all_tags if t["name"] == "planning")
    assert planning["count"] == 2

def test_get_papers_by_tag(tmp_path, monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    for pid in ["x", "y", "z"]:
        p = {"id": pid, "title": pid, "authors": [], "year": 2023,
             "venue": "neurips", "source": "", "doi": "", "abstract": "",
             "arxiv_id": pid, "pdf_url": None}
        db_module.upsert_paper(p)
    db_module.add_tag_to_paper("x", "planning")
    db_module.add_tag_to_paper("y", "planning")
    papers = db_module.get_papers_by_tag("planning")
    assert {p["id"] for p in papers} == {"x", "y"}

def test_manual_boost(tmp_path, monkeypatch):
    import pytest
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    p = {"id": "abc", "title": "T", "authors": [], "year": 2023,
         "venue": "neurips", "source": "", "doi": "", "abstract": "",
         "arxiv_id": "abc", "pdf_url": None}
    db_module.upsert_paper(p)
    db_module.update_paper("abc", manual_boost=0.3)
    papers = db_module.get_papers()
    assert papers[0]["manual_boost"] == pytest.approx(0.3)
