import os
import uuid

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

        username = f"conversation-{uuid.uuid4().hex[:10]}"
        page.locator("#usernameInput").fill(username)
        page.locator("#passwordInput").fill("LocalFix!2026")
        page.get_by_role("button", name="注册").click()
        page.get_by_text(f"已登录：{username}").wait_for(timeout=30000)

        question = page.locator("#questionInput")
        send = page.locator("#sendBtn")
        messages = page.locator("#chatMessages .content")

        question.fill("我想减肥")
        send.click()
        playwright.expect(page.locator(".bot-message .content").last).not_to_have_text("", timeout=30000)
        playwright.expect(send).to_have_text("发送", timeout=30000)
        first_answer = messages.last.inner_text()
        assert first_answer
        assert "出错了" not in first_answer
        assert "哪一餐" not in first_answer

        question.fill("那帮我安排晚餐")
        send.click()
        playwright.expect(page.locator(".bot-message .content").last).not_to_have_text("", timeout=30000)
        playwright.expect(send).to_have_text("发送", timeout=30000)
        second_answer = messages.last.inner_text()
        assert any(keyword in second_answer for keyword in ("避开", "忌口", "过敏"))

        question.fill("没有忌口")
        send.click()
        playwright.expect(page.locator(".bot-message .content").last).not_to_have_text("", timeout=30000)
        playwright.expect(send).to_have_text("发送", timeout=30000)
        third_answer = messages.last.inner_text()
        assert "晚餐" in third_answer

        assistant_count = page.locator(".bot-message .content").count()
        page.get_by_role("button", name="重新生成").last.click()
        playwright.expect(page.locator(".bot-message .content")).to_have_count(assistant_count + 1, timeout=30000)
        regenerated_answer = messages.last.inner_text()
        assert regenerated_answer
        assert "晚餐" in regenerated_answer
        actions = page.locator(".message-actions").last
        actions.get_by_role("button", name="有帮助").click()
        playwright.expect(actions.get_by_role("button", name="有帮助")).to_be_disabled()

        page.reload(wait_until="domcontentloaded")
        page.get_by_text("我想减肥", exact=True).wait_for()
        page.get_by_text("那帮我安排晚餐", exact=True).wait_for()
        assert "晚餐" in messages.last.inner_text()
        browser.close()


@pytest.mark.e2e
def test_browser_login_resets_stale_conversation_before_asking():
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script(
            """
            localStorage.setItem('userId', 'anonymous-before-login');
            localStorage.setItem('conversationId', 'stale-conversation-before-login');
            """
        )
        page.goto(base_url, wait_until="domcontentloaded")

        username = f"sessionfix-{uuid.uuid4().hex[:10]}"
        page.locator("#usernameInput").fill(username)
        page.locator("#passwordInput").fill("LocalFix!2026")
        page.get_by_role("button", name="注册").click()
        page.get_by_text(f"已登录：{username}").wait_for(timeout=30000)

        assert page.evaluate("localStorage.getItem('conversationId')") != "stale-conversation-before-login"

        question = page.locator("#questionInput")
        send = page.locator("#sendBtn")
        messages = page.locator("#chatMessages .content")
        question.fill("请给我一个简单的健康饮食建议")
        send.click()
        playwright.expect(messages.last).not_to_have_text("", timeout=30000)
        playwright.expect(send).to_have_text("发送", timeout=60000)
        answer = messages.last.inner_text()
        assert "回答未完成" not in answer
        assert "请求失败" not in answer
        browser.close()
