from core.tool_registry import build_default_tool_registry


class MealPlannerSkill:
    name = "meal_planner"
    description = "根据热量目标推荐餐食组合"

    @staticmethod
    def execute(input_text: str) -> str:
        return build_default_tool_registry().execute("meal_planner", input_text, {"fields": {"query": input_text}})
