"""Browser regression for roster-based staff authorization and audited identity access."""
import base64, json, socket, sys, threading, time
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.core.config import Settings
from test_case_identity import CaseIdentityApiTests


def login(browser, user, knowledge_requests, page_errors):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    token = base64.b64encode(f"{user.username}:password123".encode()).decode()
    context.add_init_script("sessionStorage.setItem('campusharbor.auth', "
                            + json.dumps(json.dumps({"token": token})) + ");")
    page = context.new_page()
    page.on("request", lambda request: knowledge_requests.append(request.url)
            if "/api/admin/knowledge" in request.url else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("dialog", lambda dialog: dialog.accept("高风险安全联系用途已核验" if dialog.type == "prompt" else None))
    return context, page


def case_card(page, case_id):
    return page.locator(".case-card").filter(has=page.get_by_text(f"个案 #{case_id}", exact=True))


def run():
    knowledge_requests, page_errors = [], []
    fixture = CaseIdentityApiTests(methodName="test_only_high_risk_case_is_listed_anonymously")
    fixture.setUp(); server = worker = None
    try:
        app = fixture.client.app
        app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True))
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0)); port = candidate.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        settings = Settings(ai_provider="mock", knowledge_vector_enabled=False, tool_queue_enabled=False)
        with patch("app.api.routes.get_settings", return_value=settings), sync_playwright() as pw:
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
            worker = threading.Thread(target=server.run, daemon=True); worker.start()
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline: raise RuntimeError("UI server did not start")
                time.sleep(.05)
            edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
            browser = pw.chromium.launch(headless=True, executable_path=str(edge) if edge.exists() else None)
            try:
                _, pending = login(browser, fixture.pending, knowledge_requests, page_errors)
                pending.goto(base + "/admin.html")
                expect(pending.locator("#adminGatePanel")).to_contain_text("学校导入的教职工名单")
                expect(pending.locator(".counselor-only").first).to_be_hidden()

                _, counselor = login(browser, fixture.counselor, knowledge_requests, page_errors)
                counselor.goto(base + "/admin.html")
                expect(case_card(counselor, fixture.high.id)).to_be_visible()
                expect(case_card(counselor, fixture.medium.id)).to_have_count(0)
                expect(counselor.locator("body")).not_to_contain_text("管理员身份与解封审批")
                high = case_card(counselor, fixture.high.id)
                high.get_by_role("button", name="接手个案", exact=True).click()
                expect(high.get_by_role("button", name="查看处置身份", exact=True)).to_be_visible()
                high.get_by_role("button", name="查看处置身份", exact=True).click()
                high.locator("textarea").fill("执行高风险安全联系")
                high.locator(".identity-confirmation input").check()
                high.get_by_role("button", name="确认查看", exact=True).click()
                expect(high.locator(".case-identity-details")).to_contain_text("学生甲")
                storage = counselor.evaluate("JSON.stringify({local:{...localStorage},session:{...sessionStorage}})")
                assert "学生甲" not in storage and "20260001" not in storage

                _, system = login(browser, fixture.system, knowledge_requests, page_errors)
                system.goto(base + "/admin.html")
                expect(system.locator(".counselor-only").first).to_be_hidden()
                expect(system.locator("body")).not_to_contain_text("批准解封")
                expect(system.locator("body")).not_to_contain_text("管理员身份认证")

                system.locator("#rosterFile").set_input_files({
                    "name": "staff.csv", "mimeType": "text/csv",
                    "buffer": "工号,姓名,账号,学校,学院,身份\nEMP-pending,待认证老师,pending,甲大学,甲学院,COUNSELOR\n".encode(),
                })
                system.get_by_role("button", name="导入 CSV 名单", exact=True).click()
                expect(system.locator("#accessState")).to_contain_text("辅导员账号开通 1/1 人")

                system.locator("#rosterFile").set_input_files({
                    "name": "students.csv", "mimeType": "text/csv",
                    "buffer": f"学号,姓名,学校,学院,班级\n{fixture.student.student_number},学生甲,甲大学,甲学院,甲学院1班\n".encode(),
                })
                system.get_by_role("button", name="导入 CSV 名单", exact=True).click()
                expect(system.locator("#accessState")).to_contain_text("自动归属学生 1 人")
                _, advisor = login(browser, fixture.advisor, knowledge_requests, page_errors)
                advisor.goto(base + "/admin.html")
                expect(advisor.locator("#advisorPanel")).to_contain_text(fixture.student.public_uid)
                expect(advisor.locator("#advisorPanel")).not_to_contain_text("匿名咨询内容")
                system.locator("#refreshAdmin").click()
                expect(system.locator("body")).not_to_contain_text("身份解封")
                for page in (pending, counselor, system, advisor):
                    page.wait_for_load_state("networkidle")
                    expect(page.locator("#knowledgeUploadForm, #rebuildVector, #backupVector, #knowledgeState")).to_have_count(0)
                    expect(page.locator("body")).not_to_contain_text("RAG 知识库维护")
                assert not knowledge_requests, knowledge_requests
                assert not page_errors, page_errors
                counselor.screenshot(path=str(ROOT / "target" / "case-identity-admin-ui.png"), full_page=True)
                system.screenshot(path=str(ROOT / "target" / "admin-access-governance-ui.png"), full_page=True)
                print(json.dumps({"result":"PASS", "flows":["pending gate", "role-separated UI",
                    "high-only cases", "direct audited high-risk identity access", "temporary identity",
                    "staff roster automatic authorization",
                    "no identity in browser storage", "roster auto-assignment", "advisor responsibility notice",
                    "RAG maintenance UI removed", "no knowledge API requests", "role-aware refresh",
                    "no JavaScript errors"]}, ensure_ascii=False))
            finally: browser.close()
    finally:
        if server: server.should_exit = True
        if worker: worker.join(timeout=5)
        fixture.tearDown()


if __name__ == "__main__": run()
