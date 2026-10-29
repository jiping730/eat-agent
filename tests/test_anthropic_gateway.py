from utils.llm import ModelGateway
from config import settings


def test_gateway_supports_anthropic_compatible_relay(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return {
            "choices": [{"message": {"content": "relay-ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(settings, "anthropic_api_key", "relay-key")
    monkeypatch.setattr(settings, "anthropic_api_base", "https://api.chineseall.com")
    monkeypatch.setattr(settings, "llm_primary_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_model", "glm-5.3-flash")
    monkeypatch.setattr(settings, "llm_max_attempts", 1)

    result = ModelGateway(completion_fn=completion).complete("测试中转站", user_id="relay-user")

    assert result.content == "relay-ok"
    assert calls[0]["model"] == "anthropic/glm-5.3-flash"
    assert calls[0]["api_key"] == "relay-key"
    assert calls[0]["api_base"] == "https://api.chineseall.com"
