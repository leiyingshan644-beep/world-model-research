def test_score_high_relevance():
    from filter import score_paper
    paper = {
        "title": "DreamerV3: A Generative World Model for RL",
        "abstract": "We propose a world foundation model for model-based RL exploration.",
    }
    assert score_paper(paper) > 0.5


def test_score_zero_for_unrelated():
    from filter import score_paper
    paper = {
        "title": "Attention is All You Need",
        "abstract": "A transformer architecture for natural language translation tasks.",
    }
    assert score_paper(paper) == 0.0


def test_score_is_capped_at_one():
    from filter import score_paper
    paper = {
        "title": "world model world model dreamer planet td-mpc",
        "abstract": "world model generative world model world foundation model dreamer",
    }
    assert score_paper(paper) <= 1.0
