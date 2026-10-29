from types import SimpleNamespace

from core.nutrition_estimator import estimate_nutrition


class FakeGateway:
    available = True

    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def build_request(self, task, **kwargs):
        self.calls.append(("build_request", task, kwargs))
        return SimpleNamespace(task=task)

    def complete(self, prompt, *, request, task, user_id):
        self.calls.append(("complete", prompt, request, task, user_id))
        return SimpleNamespace(content=self.content)


def test_estimate_parses_structured_json_and_records_assumptions():
    gateway = FakeGateway(
        '```json\n{"calories": 420, "protein_g": 18, "carbs_g": 58, '
        '"fat_g": 12, "confidence": "medium", "assumptions": ["按一小碗、少油估算"]}\n```'
    )

    result = estimate_nutrition(
        "番茄鸡蛋面",
        "dinner",
        "一小碗，少油",
        user_id="user-1",
        gateway=gateway,
    )

    assert result.status == "estimated"
    assert result.source == "ai"
    assert result.calories == 420
    assert result.protein_g == 18.0
    assert result.assumptions == ["按一小碗、少油估算"]
    assert gateway.calls[0][1] == "nutrition_estimate"
    assert "不要追问" in gateway.calls[1][1]
    assert '"calories":420' not in gateway.calls[1][1]


def test_estimate_never_invents_value_when_model_output_is_invalid():
    result = estimate_nutrition("一碗饭", "lunch", gateway=FakeGateway("不是 JSON"))

    assert result.status == "unavailable"
    assert result.source == "unavailable"
    assert result.calories is None


def test_estimate_skips_model_when_gateway_is_unavailable():
    gateway = FakeGateway('{"calories": 999}')
    gateway.available = False

    result = estimate_nutrition("一杯牛奶", "breakfast", gateway=gateway)

    assert result.status == "unavailable"
    assert result.calories is None
    assert gateway.calls == []
