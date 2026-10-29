import os
import uuid

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_knowledge_admin_page_uploads_and_lists_document():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5016")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url, wait_until="domcontentloaded")
        username = f"knowledge-admin-{uuid.uuid4().hex[:10]}"
        page.locator("#usernameInput").fill(username)
        page.locator("#passwordInput").fill("LocalFix!2026")
        page.get_by_role("button", name="注册").click()
        page.get_by_text(f"已登录：{username}").wait_for(timeout=30000)
        page.goto(f"{base_url}/admin/knowledge", wait_until="domcontentloaded")
        page.get_by_role("heading", name="知识库管理").wait_for()

        page.locator("#knowledgeApiKey").fill("p1-6-admin")
        page.get_by_role("button", name="保存凭据").click()
        playwright.expect(page.locator("#knowledgeSummary")).to_contain_text("共", timeout=30000)

        title = f"浏览器验收文档-{uuid.uuid4().hex[:8]}"
        page.locator("#knowledgeTitle").fill(title)
        page.locator("#knowledgeContent").fill("蛋白质是重要的营养素。")
        page.get_by_role("button", name="上传为草稿").click()
        page.get_by_text(title).wait_for()
        assert page.get_by_text("draft", exact=True).count() == 1
        browser.close()
