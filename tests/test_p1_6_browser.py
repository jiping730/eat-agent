import os
import uuid

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_react_profile_page_saves_health_goal():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(base_url, wait_until="domcontentloaded")
        page.get_by_role("button", name="注册").click()
        page.get_by_label("用户名").fill(f"react-profile-{uuid.uuid4().hex[:10]}")
        page.get_by_label("密码").fill("LocalFix!2026")
        page.get_by_role("button", name="创建我的账号").click()
        page.get_by_role("heading", name="今天，吃顿舒服的饭。").wait_for(timeout=30000)
        page.get_by_role("link", name="我的").click()
        page.get_by_role("heading", name="我的健康档案").wait_for()
        page.get_by_label("当前目标").select_option(label="温和减脂")
        page.get_by_role("button", name="保存健康档案").click()
        page.get_by_text("健康档案已保存").wait_for(timeout=30000)
        browser.close()
