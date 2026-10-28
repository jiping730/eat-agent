import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_knowledge_admin_page_uploads_and_lists_document():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5016")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{base_url}/admin/knowledge", wait_until="domcontentloaded")
        page.get_by_role("heading", name="知识库管理").wait_for()

        page.locator("#knowledgeApiKey").fill("p1-6-admin")
        page.get_by_role("button", name="保存凭据").click()
        page.get_by_text("共 0 个文档").wait_for()

        page.locator("#knowledgeTitle").fill("浏览器验收文档")
        page.locator("#knowledgeContent").fill("蛋白质是重要的营养素。")
        page.get_by_role("button", name="上传为草稿").click()
        page.get_by_text("浏览器验收文档").wait_for()
        assert page.get_by_text("draft", exact=True).count() == 1
        browser.close()
