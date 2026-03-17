import os
import importlib

skill_registry = {}  # 改名为 skill_registry

# 获取 skills 目录的路径
skills_dir = os.path.join(os.path.dirname(__file__), "skills")
if os.path.exists(skills_dir):
    for skill_name in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, skill_name)
        if os.path.isdir(skill_path) and not skill_name.startswith("__"):
            try:
                module = importlib.import_module(f"core.skills.{skill_name}.skill")
                for attr in dir(module):
                    cls = getattr(module, attr)
                    if hasattr(cls, "name") and hasattr(cls, "execute"):
                        skill_registry[cls.name] = cls
                        print(f"Loaded skill: {cls.name}")
            except ImportError as e:
                print(f"Warning: Could not import skill {skill_name}: {e}")

def get_skill(name: str):
    return skill_registry.get(name)