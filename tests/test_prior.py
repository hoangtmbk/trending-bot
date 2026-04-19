"""Tests for scoring.prior.org_prior."""
from scoring.prior import org_prior


PRIORS = {
    "anthropic.com": 2.0,
    "openai.com": 2.0,
    "github.com/openai": 1.8,
    "huggingface.co/meta-llama": 1.8,
    "github.com": 1.1,
}


def test_exact_host_match():
    assert org_prior("https://anthropic.com/news/claude-4.7", PRIORS) == 2.0


def test_www_prefix_normalized():
    assert org_prior("https://www.anthropic.com/news/x", PRIORS) == 2.0


def test_host_path_prefix_beats_host():
    """github.com/openai should win over the generic github.com entry."""
    assert org_prior("https://github.com/openai/gpt-5", PRIORS) == 1.8


def test_unrelated_host_path_falls_back_to_host():
    assert org_prior("https://github.com/random/junk-project", PRIORS) == 1.1


def test_unknown_host_is_one():
    assert org_prior("https://random-blog.net/post", PRIORS) == 1.0


def test_empty_priors_is_one():
    assert org_prior("https://anthropic.com/x", {}) == 1.0


def test_empty_url_is_one():
    assert org_prior("", PRIORS) == 1.0


def test_malformed_url_is_one():
    # urlparse of garbage doesn't raise; just yields empty host → fall back.
    assert org_prior("not a url", PRIORS) == 1.0


def test_case_insensitive():
    assert org_prior("https://ANTHROPIC.COM/news/x", PRIORS) == 2.0
    priors_mixed = {"Anthropic.com": 3.0}
    assert org_prior("https://anthropic.com/x", priors_mixed) == 3.0


def test_hf_meta_llama_path_match():
    assert org_prior("https://huggingface.co/meta-llama/Llama-3", PRIORS) == 1.8
    # Different HF user gets no boost under this priors dict.
    assert org_prior("https://huggingface.co/random-user/thing", PRIORS) == 1.0
