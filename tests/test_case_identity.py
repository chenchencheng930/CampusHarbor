import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import router
from app.core.config import Settings
from app.core.database import Base, get_db
from app.models.entities import (CaseIdentityAccess, ChatMessage, ChatSession,
                                 IdentityAccessAudit,
                                 PsychologicalReport, RiskCase, UserAccount)
from app.services.privacy import PrivacySanitizer
from app.services.tool_queue import ToolQueueService


class CaseIdentityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'access.db'}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()
        self.student = self.user("student", "学生甲", student_number="20260001")
        self.system = self.user("system", "系统管理员", role="SYSTEM_ADMIN", verified=True, scope="SCHOOL")
        self.counselor = self.user("counselor", "心理老师", role="COUNSELOR", verified=True)
        self.same_name = self.user("same-name", "心理老师", role="COUNSELOR", verified=True)
        self.pending = self.user("pending", "待认证老师", role="COUNSELOR", verified=False)
        self.advisor = self.user("advisor", "辅导员", role="ADVISOR", verified=True)
        self.other_advisor = self.user("other-advisor", "其他辅导员", role="ADVISOR", verified=True)
        self.high = self.case(self.student, "HIGH")
        self.medium = self.case(self.student, "MEDIUM")
        self.db.commit()
        app = FastAPI(); app.include_router(router)
        def override():
            with self.sessions() as db: yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.db.close(); self.engine.dispose(); self.temp.cleanup()

    def user(self, username, name, *, role="NONE", verified=True, scope="COLLEGE", student_number=None):
        admin = role != "NONE"
        user = UserAccount(username=username, display_name=name,
            password_hash=hashlib.sha256(b"password123").hexdigest(),
            roles_csv="ROLE_ADMIN,ROLE_USER" if admin else "ROLE_USER",
            public_uid=f"UID-{username}", student_number=student_number,
            identity_verified=not admin, school_name="甲大学", college_name="甲学院",
            admin_scope=scope if admin else "NONE", admin_role=role,
            admin_verification_status="VERIFIED" if verified else "PENDING",
            admin_employee_number=f"EMP-{username}" if admin else None)
        self.db.add(user); self.db.flush(); return user

    def case(self, student, risk):
        session = ChatSession(public_id=f"session-{student.id}-{risk}", title="匿名会话", user_id=student.id)
        self.db.add(session); self.db.flush()
        self.db.add(ChatMessage(user_id=student.id, session_id=session.id, role="USER", content="匿名咨询内容"))
        report = PsychologicalReport(user_id=student.id, session_id=session.id, content="匿名咨询内容",
            intent="RISK", emotion="ANXIETY", emotion_score=.8, risk_level=risk,
            confidence=.9, summary="匿名评估摘要")
        self.db.add(report); self.db.flush()
        case = RiskCase(report_id=report.id, risk_level=risk, status="OPEN", summary="私密摘要")
        self.db.add(case); self.db.flush(); return case

    def request(self, method, path, user, **kwargs):
        token = base64.b64encode(f"{user.username}:password123".encode()).decode()
        return self.client.request(method, path, headers={"Authorization": f"Basic {token}"}, **kwargs)

    def claim(self, case=None, user=None):
        case, user = case or self.high, user or self.counselor
        return self.request("POST", f"/api/admin/cases/{case.id}/acknowledge", user, json={"note": "接手"})

    def reveal(self, user=None):
        return self.request("POST", f"/api/admin/cases/{self.high.id}/identity", user or self.counselor,
                            json={"reason": "执行已审批安全联系", "emergencyConfirmed": True})

    def test_unverified_admin_cannot_enter_admin_features(self):
        for path in ["/api/admin/cases", "/api/admin/classes", "/api/admin/knowledge/status"]:
            self.assertEqual(self.request("GET", path, self.pending).status_code, 403)

    def test_system_admin_cannot_access_risk_data(self):
        for path in ["/api/admin/cases", "/api/admin/reports", f"/api/admin/conversations/{self.high.id}"]:
            self.assertEqual(self.request("GET", path, self.system).status_code, 403)
        self.assertEqual(self.request("GET", "/api/admin/access/verification-requests", self.system).status_code, 404)

    def test_counselor_cannot_manage_system_settings(self):
        for path in ["/api/admin/knowledge/status", "/api/admin/classes"]:
            self.assertEqual(self.request("GET", path, self.counselor).status_code, 403)

    def test_only_high_risk_case_is_listed_anonymously(self):
        response = self.request("GET", "/api/admin/cases", self.counselor)
        self.assertEqual([item["id"] for item in response.json()], [self.high.id])
        for secret in ["学生甲", "20260001", "私密摘要", "匿名咨询内容"]:
            self.assertNotIn(secret, response.text)

    def test_medium_cannot_be_claimed(self):
        self.assertEqual(self.claim(self.medium).status_code, 409)
        self.assertIsNone(self.db.get(CaseIdentityAccess, self.medium.id))

    def test_high_identity_requires_claim_and_audited_reason(self):
        self.assertEqual(self.reveal().status_code, 403)
        self.assertEqual(self.claim().status_code, 200)
        response = self.reveal()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "学生甲")
        self.assertIn("访问原因已审计", response.json()["basis"])
        self.assertNotIn("content", response.json())

    def test_same_display_name_does_not_share_approval(self):
        self.claim()
        self.assertEqual(self.reveal(self.same_name).status_code, 403)
        self.assertEqual(self.claim(user=self.same_name).status_code, 409)

    def test_removed_disclosure_approval_endpoints_are_not_available(self):
        self.assertEqual(self.request("GET", "/api/admin/access/disclosure-requests", self.system).status_code, 404)
        self.assertEqual(self.request("POST", f"/api/admin/cases/{self.high.id}/identity-request",
                                      self.counselor, json={"reason": "不再使用"}).status_code, 404)

    def test_reveal_attempts_are_audited(self):
        self.reveal(); self.claim(); self.reveal()
        rows = self.db.query(IdentityAccessAudit).all()
        self.assertTrue(any(row.allowed for row in rows)); self.assertTrue(any(not row.allowed for row in rows))

    def test_system_admin_has_no_identity_approval_queue(self):
        self.assertEqual(self.request("GET", "/api/admin/access/disclosure-requests", self.system).status_code, 404)

    def test_advisor_only_sees_assigned_student_crisis_notice(self):
        self.student.advisor_admin_id = self.advisor.id; self.db.commit()
        response = self.request("GET", "/api/admin/advisor-alerts", self.advisor)
        self.assertEqual(response.json()[0]["studentUid"], self.student.public_uid)
        self.assertNotIn("匿名咨询内容", response.text)
        self.assertEqual(self.request("GET", "/api/admin/advisor-alerts", self.other_advisor).json(), [])
        self.assertEqual(self.request("GET", "/api/admin/cases", self.advisor).status_code, 403)

    def test_staff_roster_automatically_provisions_admin_registration(self):
        roster = "工号,姓名,账号,学校,学院,身份\nE10086,新老师,new-counselor,甲大学,甲学院,COUNSELOR\n"
        imported = self.request("POST", "/api/admin/roster/import", self.system,
                                files={"file": ("staff.csv", roster.encode(), "text/csv")})
        self.assertEqual(imported.status_code, 200, imported.text)
        response = self.client.post("/api/auth/register", json={
            "username": "new-counselor", "password": "password123", "displayName": "新老师",
            "accountType": "admin", "adminRole": "COUNSELOR", "employeeNumber": "E10086",
            "adminScope": "NONE", "schoolName": "", "collegeName": "",
        })
        self.assertEqual(response.status_code, 201, response.text)
        profile = response.json()["profile"]
        self.assertEqual(profile["adminVerificationStatus"], "VERIFIED")
        self.assertEqual(profile["adminRole"], "COUNSELOR")
        self.assertEqual(profile["adminScope"], "COLLEGE")
        token = response.json()["token"]
        result = self.client.get("/api/admin/cases", headers={"Authorization": f"Basic {token}"})
        self.assertEqual(result.status_code, 200)

    def test_public_registration_cannot_create_system_admin(self):
        response = self.client.post("/api/auth/register", json={
            "username": "attacker", "password": "password123", "displayName": "攻击者",
            "accountType": "admin", "adminRole": "SYSTEM_ADMIN", "employeeNumber": "E1",
            "adminScope": "SCHOOL",
            "schoolName": "甲大学", "collegeName": "甲学院",
        })
        # SYSTEM_ADMIN is not a public-registration role at all; schema validation
        # rejects it before roster matching is attempted.
        self.assertEqual(response.status_code, 422)

    def test_tool_plan_creates_case_only_for_high(self):
        service = ToolQueueService(self.db, Settings(tool_queue_enabled=True))
        self.assertEqual([j.kind for j in service.enqueue_report(self.medium.report_id, "MEDIUM")], ["EXCEL_REPORT"])
        self.assertIn("CASE_CREATE", [j.kind for j in service.enqueue_report(self.high.report_id, "HIGH")])

    def test_privacy_sanitizer_masks_identity_context(self):
        output = PrivacySanitizer().sanitize("我是计算机学院23级张伟，住在宿舍3栋201，电话13800138000")
        for secret in ["计算机学院", "23级", "张伟", "13800138000"]:
            self.assertNotIn(secret, output)


if __name__ == "__main__": unittest.main()
