from models import RawItem
from scoring.momentum import compute_momentum_score, compute_final_score


def test_github_momentum_new_repo():
    """3-day-old repo with 500 stars = 500/3 = ~167 momentum"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 500, "age_days": 3},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert abs(score - 500 / 3) < 0.01


def test_github_momentum_old_repo():
    """5-year-old repo (1825 days) with 100K stars = ~55 momentum"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 100000, "age_days": 1825},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert abs(score - 100000 / 1825) < 0.1


def test_github_momentum_defaults_age_to_365():
    """Missing age_days defaults to 365"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 3000},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert abs(score - 3000 / 365) < 0.1


def test_github_momentum_zero_age_clamped():
    """age_days=0 should be clamped to 1 to avoid division by zero"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 200, "age_days": 0},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert score == 200.0


def test_reddit_momentum():
    item = RawItem(title="test", url="http://test.com", source="reddit",
                   description="", metrics={"score": 500, "upvote_ratio": 0.95},
                   timestamp="2026-04-08T01:00:00Z")
    score = compute_momentum_score(item)
    assert score > 0


def test_hackernews_momentum():
    item = RawItem(title="test", url="http://test.com", source="hackernews",
                   description="", metrics={"points": 350}, timestamp="2026-04-08T01:00:00Z")
    score = compute_momentum_score(item)
    assert score > 0


def test_arxiv_momentum():
    item = RawItem(title="test", url="http://test.com", source="arxiv",
                   description="", metrics={"citation_count": 15, "influential_citations": 3},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert score > 0


def test_huggingface_momentum():
    item = RawItem(title="test", url="http://test.com", source="huggingface",
                   description="", metrics={"downloads": 50000, "likes": 1200},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert score > 0


def test_twitter_momentum():
    item = RawItem(title="test", url="http://test.com", source="twitter",
                   description="", metrics={"retweets": 1200, "quotes": 300},
                   timestamp="2026-04-08T01:00:00Z")
    score = compute_momentum_score(item)
    assert score > 0


def test_final_score_with_cross_platform_boost():
    boost_config = {2: 1.5, 3: 2.5, 4: 4.0}
    score = compute_final_score(
        momentum_score=1.0, age_hours=0, freshness_half_life=48,
        num_sources=3, boost_config=boost_config,
    )
    assert score == 2.5


def test_final_score_decays_with_age():
    boost_config = {2: 1.5, 3: 2.5, 4: 4.0}
    fresh = compute_final_score(1.0, age_hours=0, freshness_half_life=48,
                                num_sources=1, boost_config=boost_config)
    old = compute_final_score(1.0, age_hours=96, freshness_half_life=48,
                              num_sources=1, boost_config=boost_config)
    assert fresh > old
