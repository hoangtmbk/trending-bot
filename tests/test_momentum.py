from models import RawItem
from scoring.momentum import compute_momentum_score, compute_final_score


def test_github_momentum():
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 3000}, timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert score > 0


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
