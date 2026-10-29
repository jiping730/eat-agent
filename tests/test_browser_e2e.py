import os
import uuid

import pytest

if os.getenv("RUN_BROWSER_E2E") != "1":
    pytest.skip("set RUN_BROWSER_E2E=1 to run browser E2E", allow_module_level=True)

playwright = pytest.importorskip("playwright.sync_api")


def register(page, prefix: str) -> str:
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    page.goto(os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000"), wait_until="domcontentloaded")
    page.get_by_role("button", name="注册").click()
    page.get_by_label("用户名").fill(username)
    page.get_by_label("密码").fill("LocalFix!2026")
    page.get_by_role("button", name="创建我的账号").click()
    page.get_by_role("heading", name="今天，吃顿舒服的饭。").wait_for(timeout=30000)
    return username


@pytest.mark.e2e
def test_react_frontend_auth_navigation_and_chat():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        register(page, "react-chat")

        page.get_by_role("link", name="AI 助手").click()
        page.get_by_role("heading", name="新对话").wait_for()
        question = page.locator("#chat-input")
        question.fill("我想减肥")
        page.get_by_role("button", name="发送问题").click()
        page.get_by_text("我想减肥", exact=True).wait_for(timeout=30000)
        assert page.get_by_text("回答未完成").count() == 0
        assert page.get_by_text("哪一餐", exact=False).count() == 0

        page.get_by_role("link", name="饮食记录").click()
        page.get_by_role("heading", name="饮食记录").wait_for()
        page.get_by_role("link", name="营养看板").click()
        page.get_by_role("heading", name="营养看板").wait_for()
        page.get_by_role("link", name="我的").click()
        page.get_by_role("heading", name="我的健康档案").wait_for()
        browser.close()


@pytest.mark.e2e
def test_react_frontend_personal_knowledge_flow():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        register(page, "react-knowledge")
        page.get_by_role("link", name="个人知识库").click()
        page.get_by_role("heading", name="个人知识库").wait_for()

        page.get_by_role("button", name="添加文档").click()
        title = f"浏览器验收笔记-{uuid.uuid4().hex[:8]}"
        page.get_by_label("标题").fill(title)
        page.get_by_label("内容").fill("我的个人饮食目标是每天优先选择高纤维食物。")
        page.get_by_role("button", name="添加并开始构建索引").click()
        page.get_by_text(title, exact=True).wait_for(timeout=30000)

        page.get_by_label("检索关键词").fill("高纤维")
        page.get_by_role("button", name="查找").click()
        page.get_by_text(title, exact=True).last.wait_for()
        browser.close()
