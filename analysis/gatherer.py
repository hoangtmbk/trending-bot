from __future__ import annotations
import logging
import requests
from urllib.parse import urlparse
from models import ScoredItem

logger = logging.getLogger(__name__)


def gather_source_material(item: ScoredItem) -> dict:
    material: dict = {"title": item.title, "url": item.url, "description": item.description}

    url = item.url
    parsed = urlparse(url)

    if "github.com" in parsed.netloc:
        material["readme"] = _fetch_github_readme(url)
        material["competitors"] = _search_github_similar(item.title)
    elif "arxiv.org" in parsed.netloc:
        material["abstract"] = item.description
        material["pdf_url"] = item.raw_items[0].metrics.get("pdf_url", "")
    elif "huggingface.co" in parsed.netloc:
        material["readme"] = _fetch_hf_readme(url)
    elif "reddit.com" in parsed.netloc:
        material["comments"] = _fetch_reddit_comments(url)

    for raw in item.raw_items:
        if raw.source == "hackernews" and "objectID" in raw.metrics:
            material["hn_comments"] = _fetch_hn_comments(raw.metrics["objectID"])

    return material


def _fetch_github_readme(repo_url: str) -> str:
    try:
        parts = urlparse(repo_url).path.strip("/").split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md"
            resp = requests.get(raw_url, timeout=15)
            if resp.status_code == 200:
                return resp.text[:5000]
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md"
            resp = requests.get(raw_url, timeout=15)
            if resp.status_code == 200:
                return resp.text[:5000]
    except Exception as e:
        logger.warning(f"Failed to fetch GitHub README: {e}")
    return ""


def _search_github_similar(title: str) -> str:
    try:
        query = title.split("/")[-1] if "/" in title else title
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": "stars", "per_page": 5}
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            repos = resp.json().get("items", [])
            lines = []
            for r in repos[:5]:
                lines.append(f"- {r['full_name']} ({r['stargazers_count']} stars): {r.get('description', '')}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning(f"GitHub competitor search failed: {e}")
    return ""


def _fetch_hf_readme(model_url: str) -> str:
    try:
        model_id = urlparse(model_url).path.strip("/")
        api_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 200:
            return resp.text[:5000]
    except Exception as e:
        logger.warning(f"Failed to fetch HF README: {e}")
    return ""


def _fetch_reddit_comments(thread_url: str) -> str:
    try:
        json_url = thread_url.rstrip("/") + ".json"
        headers = {"User-Agent": "trending-bot/1.0"}
        resp = requests.get(json_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) > 1:
                comments = data[1].get("data", {}).get("children", [])[:10]
                lines = []
                for c in comments:
                    body = c.get("data", {}).get("body", "")
                    if body:
                        lines.append(body[:300])
                return "\n---\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch Reddit comments: {e}")
    return ""


def _fetch_hn_comments(object_id: str) -> str:
    try:
        url = f"https://hn.algolia.com/api/v1/items/{object_id}"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            children = data.get("children", [])[:10]
            lines = [c.get("text", "")[:300] for c in children if c.get("text")]
            return "\n---\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch HN comments: {e}")
    return ""
