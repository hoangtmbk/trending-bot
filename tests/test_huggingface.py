from unittest.mock import patch, MagicMock
from collectors.huggingface import HuggingFaceCollector
from models import RawItem


def _mock_model():
    m = MagicMock()
    m.id = "meta-llama/Llama-3-70B"
    m.downloads = 50000
    m.likes = 1200
    m.tags = ["text-generation", "llm"]
    m.created_at.isoformat.return_value = "2026-04-07T00:00:00Z"
    m.pipeline_tag = "text-generation"
    return m


def test_huggingface_collector_returns_raw_items():
    mock_model = _mock_model()
    with patch("collectors.huggingface.HfApi") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.list_models.return_value = [mock_model]
        mock_api_cls.return_value = mock_api

        collector = HuggingFaceCollector()
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "huggingface"
        assert "downloads" in items[0].metrics


def test_huggingface_collector_saves(tmp_data_dir):
    mock_model = _mock_model()
    with patch("collectors.huggingface.HfApi") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.list_models.return_value = [mock_model]
        mock_api_cls.return_value = mock_api

        collector = HuggingFaceCollector()
        collector.run(tmp_data_dir)
        assert (tmp_data_dir / "raw" / "huggingface.json").exists()
