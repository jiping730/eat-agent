import os

import pytest

if os.getenv("RUN_BROWSER_E2E") != "1":
    pytest.skip("set RUN_BROWSER_E2E=1 to run browser E2E", allow_module_level=True)

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_browser_goal_advice_then_explicit_meal_plan():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url, wait_until="domcontentloaded")

        question = page.locator("#questionInput")
        send = page.locator("#sendBtn")
        messages = page.locator("#chatMessages .content")

        question.fill("我想减肥")
        send.click()
        page.get_by_text("如果目标是减脂", exact=False).wait_for()
        assert "哪一餐" not in messages.last.inner_text()

        question.fill("那帮我安排晚餐")
        send.click()
        page.get_by_text("你有需要避开的食物", exact=False).wait_for()

        question.fill("没有忌口")
        send.click()
        page.get_by_text("我按晚餐", exact=False).wait_for()

        page.get_by_role("button", name="重新生成").last.click()
        page.get_by_text("我按晚餐", exact=False).last.wait_for()
        actions = page.locator(".message-actions").last
        actions.get_by_role("button", name="有帮助").click()
        playwright.expect(actions.get_by_role("button", name="有帮助")).to_be_disabled()

        page.reload(wait_until="domcontentloaded")
        page.get_by_text("我想减肥", exact=True).wait_for()
        page.get_by_text("我按晚餐", exact=False).wait_for()
        browser.close()
