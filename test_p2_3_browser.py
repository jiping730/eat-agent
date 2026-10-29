import os
import uuid

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_personal_knowledge_page_imports_retrieves_and_deletes_document():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5017")
    title = f"浏览器个人笔记-{uuid.uuid4().hex[:8]}"

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url, wait_until="domcontentloaded")
        username = f"personal-knowledge-{uuid.uuid4().hex[:10]}"
        page.locator("#usernameInput").fill(username)
        page.locator("#passwordInput").fill("LocalFix!2026")
        page.get_by_role("button", name="注册").click()
        page.get_by_text(f"已登录：{username}").wait_for(timeout=30000)
        page.goto(f"{base_url}/me/knowledge", wait_until="domcontentloaded")
        page.get_by_role("heading", name="我的知识").wait_for()

        page.locator("#personalKnowledgeTitle").fill(title)
        page.locator("#personalKnowledgeContent").fill("我的个人目标是每天优先选择高纤维食物。")
        page.get_by_role("button", name="导入并构建索引").click()

        row = page.locator("#personalKnowledgeDocuments tr").filter(has_text=title)
        row.wait_for()
        assert row.get_by_text("published", exact=True).count() == 1

        page.locator("#personalKnowledgeQuery").fill("我的个人饮食目标是什么")
        page.get_by_role("button", name="测试检索").click()
        result = page.locator("#personalKnowledgeResult")
        page.wait_for_function(
            "() => document.querySelector('#personalKnowledgeResult')?.textContent?.includes('personal_knowledge')"
        )
        assert "personal_knowledge" in (result.text_content() or "")
        assert title in (result.text_content() or "")

        page.on("dialog", lambda dialog: dialog.accept())
        row.get_by_role("button", name="删除").click()
        row.wait_for(state="detached")
        assert page.locator("#personalKnowledgeDocuments tr").filter(has_text=title).count() == 0
        browser.close()
