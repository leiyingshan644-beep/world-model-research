def test_score_high_relevance_rl():
    from filter import score_paper
    # RL-based world model paper — lower score after de-prioritising dreamer/RL weights
    paper = {
        "title": "DreamerV3: A Generative World Model for RL",
        "abstract": "We propose a world foundation model for model-based RL exploration.",
    }
    assert score_paper(paper) > 0.3


def test_score_high_relevance_visual():
    from filter import score_paper
    # Visual generation world model paper — should score high with new keywords
    paper = {
        "title": "Cosmos: A Visual World Model for Video Generation",
        "abstract": "We present a generative world model based on video diffusion for text-to-video synthesis.",
    }
    assert score_paper(paper) > 0.4


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
