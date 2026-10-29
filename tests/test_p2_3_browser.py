import os
import uuid

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_react_frontend_meal_record_is_explicitly_local():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base_url, wait_until="domcontentloaded")
        page.get_by_role("button", name="注册").click()
        page.get_by_label("用户名").fill(f"react-record-{uuid.uuid4().hex[:10]}")
        page.get_by_label("密码").fill("LocalFix!2026")
        page.get_by_role("button", name="创建我的账号").click()
        page.get_by_role("heading", name="今天，吃顿舒服的饭。").wait_for(timeout=30000)
        page.get_by_role("link", name="饮食记录").click()
        page.get_by_role("heading", name="饮食记录").wait_for()
        page.get_by_text("当前仅保存在本机").wait_for()
        page.get_by_role("button", name="记一餐").click()
        page.get_by_label("吃了什么").fill("番茄鸡蛋面")
        page.get_by_role("button", name="保存这条记录").click()
        page.get_by_text("番茄鸡蛋面", exact=True).wait_for()
        page.get_by_text("已保存到本机饮食记录").wait_for(timeout=30000)
        browser.close()
