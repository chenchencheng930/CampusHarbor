"""Case-bound access to minimal identity, never to consultation content."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import (
    CampusClass, ClassMembership, CaseConsentEvent, CaseIdentityAccess,
    IdentityAccessAudit, PsychologicalReport, RiskCase, UserAccount,
)

ACTIVE_STATUSES = {"ACKNOWLEDGED", "REFERRED"}


class CaseAccessError(ValueError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


class CaseIdentityService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def valid_scope(admin: UserAccount) -> bool:
        return bool(
            "ROLE_ADMIN" in admin.roles and admin.account_status == "ACTIVE"
            and admin.admin_verification_status == "VERIFIED"
            and admin.admin_role in {"COUNSELOR", "ADVISOR", "DEMO_ADMIN"}
            and admin.admin_scope in {"SCHOOL", "COLLEGE"}
            and (admin.school_name or "").strip()
            and (admin.admin_scope == "SCHOOL" or (admin.college_name or "").strip())
        )

    def scoped_case(self, admin: UserAccount, case_id: int):
        # Serializes claim/status/consent changes on the primary database.
        case = self.db.scalar(select(RiskCase).where(RiskCase.id == case_id).with_for_update())
        report = self.db.get(PsychologicalReport, case.report_id) if case else None
        student = self.db.get(UserAccount, report.user_id) if report else None
        if (not student or not self.valid_scope(admin)
                or student.school_name != admin.school_name
                or (admin.admin_scope == "COLLEGE" and student.college_name != admin.college_name)):
            raise CaseAccessError("个案不存在或不在管理范围内", 404)
        return case, student

    def _binding(self, case_id: int):
        return self.db.scalar(select(CaseIdentityAccess).where(
            CaseIdentityAccess.case_id == case_id).with_for_update())

    def require_handler(self, admin: UserAccount, case_id: int, *, allow_closed: bool = False):
        case, student = self.scoped_case(admin, case_id)
        binding = self._binding(case_id)
        if not binding or binding.admin_id != admin.id:
            raise CaseAccessError("仅当前个案接手人可以执行此操作")
        if case.status not in ACTIVE_STATUSES and not (allow_closed and case.status == "CLOSED"):
            raise CaseAccessError("个案当前状态不允许此操作", 409)
        return case, student, binding

    def claim(self, admin: UserAccount, case_id: int):
        case, _ = self.scoped_case(admin, case_id)
        if admin.admin_role not in {"COUNSELOR", "DEMO_ADMIN"}:
            raise CaseAccessError("仅心理中心老师可以接手风险事件")
        if case.risk_level != "HIGH":
            raise CaseAccessError("只有高风险事件可以进入人工个案流程", 409)
        binding = self._binding(case_id)
        if binding and binding.admin_id != admin.id:
            raise CaseAccessError("该个案已由其他管理员接手，不能重复认领", 409)
        if case.status == "CLOSED":
            raise CaseAccessError("已关闭个案不能接手", 409)
        if binding:
            return case  # Idempotent; do not revert a referred case.
        self.db.add(CaseIdentityAccess(case_id=case_id, admin_id=admin.id))
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise CaseAccessError("个案已被接手，请刷新后重试", 409) from exc
        return case

    def consent_state(self, binding: CaseIdentityAccess | None) -> str:
        if not binding:
            return "NOT_REQUESTED"
        if binding.student_consent:
            return "GRANTED"
        event = self.db.query(CaseConsentEvent).filter(
            CaseConsentEvent.case_id == binding.case_id,
            CaseConsentEvent.admin_id == binding.admin_id,
        ).order_by(CaseConsentEvent.id.desc()).first()
        return event.decision if event else "PENDING"

    def reveal(self, admin: UserAccount, case_id: int, reason: str, emergency_confirmed: bool = False):
        reason = reason.strip()
        try:
            if not reason:
                raise CaseAccessError("必须填写查看原因", 422)
            case, student, binding = self.require_handler(admin, case_id)
            if admin.admin_role not in {"COUNSELOR", "DEMO_ADMIN"} or case.risk_level != "HIGH":
                raise CaseAccessError("只有心理中心老师可以查看高风险个案必要身份")
            if not emergency_confirmed:
                raise CaseAccessError("请确认仅为高风险安全联系和人工处置查看必要身份")
        except CaseAccessError:
            self.db.add(IdentityAccessAudit(case_id=case_id, admin_id=admin.id,
                                           reason=reason or "未填写原因", allowed=False))
            self.db.commit()
            raise
        classes = self.db.query(CampusClass).join(
            ClassMembership, ClassMembership.class_id == CampusClass.id,
        ).filter(ClassMembership.student_id == student.id,
                 ClassMembership.status == "APPROVED",
                 CampusClass.school_name == admin.school_name,
                 CampusClass.status == "ACTIVE")
        if admin.admin_scope == "COLLEGE":
            classes = classes.filter(CampusClass.college_name == admin.college_name)
        payload = {
            "name": student.display_name, "studentNumber": student.student_number,
            "studentUid": student.public_uid, "schoolName": student.school_name,
            "collegeName": student.college_name, "classes": [c.name for c in classes.all()],
            "identityStatus": "已按学校导入名册核验" if student.identity_verified else "身份尚未完成学校名册核验",
            "contactStatus": "未接入已核验联系方式，请通过学校授权通讯录联系",
            "basis": "高风险个案接手人直接处置（访问原因已审计）",
        }
        self.db.add(IdentityAccessAudit(case_id=case_id, admin_id=admin.id, reason=reason, allowed=True))
        self.db.commit()
        return payload

    def _student_case(self, student: UserAccount, case_id: int):
        if "ROLE_ADMIN" in student.roles or student.account_status != "ACTIVE":
            raise CaseAccessError("仅学生本人可以管理联系授权")
        case = self.db.scalar(select(RiskCase).where(RiskCase.id == case_id).with_for_update())
        report = self.db.get(PsychologicalReport, case.report_id) if case else None
        if not report or report.user_id != student.id:
            raise CaseAccessError("联系请求不存在", 404)
        return case

    def student_requests(self, student: UserAccount):
        if "ROLE_ADMIN" in student.roles or student.account_status != "ACTIVE":
            raise CaseAccessError("仅学生本人可以读取联系请求")
        rows = self.db.query(RiskCase, CaseIdentityAccess, UserAccount).join(
            PsychologicalReport, PsychologicalReport.id == RiskCase.report_id,
        ).join(CaseIdentityAccess, CaseIdentityAccess.case_id == RiskCase.id).join(
            UserAccount, UserAccount.id == CaseIdentityAccess.admin_id,
        ).filter(PsychologicalReport.user_id == student.id,
                 RiskCase.status.in_(ACTIVE_STATUSES | {"CLOSED"}),
                 RiskCase.risk_level == "HIGH").order_by(
                     RiskCase.updated_at.desc()).limit(100).all()
        return [{"caseId": case.id, "administrator": admin.display_name,
                 "organization": " · ".join(filter(None, [admin.school_name, admin.college_name])),
                 "riskLevel": case.risk_level, "status": case.status,
                 "consent": "NOT_REQUIRED"}
                for case, binding, admin in rows
                if self.valid_scope(admin) and student.school_name == admin.school_name
                and (admin.admin_scope == "SCHOOL" or student.college_name == admin.college_name)]

    def set_consent(self, student: UserAccount, case_id: int, decision: str):
        raise CaseAccessError("新权限模型不再通过学生端开放中风险身份", 410)

    def audits(self, admin: UserAccount, case_id: int):
        self.require_handler(admin, case_id, allow_closed=True)
        return self._audit_rows(case_id)

    def student_audits(self, student: UserAccount, case_id: int):
        self._student_case(student, case_id)
        return self._audit_rows(case_id)

    def _audit_rows(self, case_id: int):
        rows = self.db.query(IdentityAccessAudit, UserAccount.display_name).join(
            UserAccount, UserAccount.id == IdentityAccessAudit.admin_id,
        ).filter(IdentityAccessAudit.case_id == case_id).order_by(
            IdentityAccessAudit.id.desc()).limit(100).all()
        return [{"id": row.id, "administrator": name, "reason": row.reason,
                 "allowed": row.allowed, "createdAt": row.created_at} for row, name in rows]
