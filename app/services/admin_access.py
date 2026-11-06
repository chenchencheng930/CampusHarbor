from sqlalchemy.orm import Session

from app.models.entities import PsychologicalReport, RiskCase, UserAccount


class AdminAccessError(ValueError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


class AdminAccessService:
    def __init__(self, db: Session):
        self.db = db

    def advisor_alerts(self, advisor: UserAccount):
        if advisor.admin_role not in {"ADVISOR", "DEMO_ADMIN"} or advisor.admin_verification_status != "VERIFIED":
            raise AdminAccessError("仅已认证辅导员可以读取危机通知")
        query = self.db.query(RiskCase, PsychologicalReport, UserAccount).join(
            PsychologicalReport, PsychologicalReport.id == RiskCase.report_id,
        ).join(UserAccount, UserAccount.id == PsychologicalReport.user_id).filter(
            RiskCase.risk_level == "HIGH",
        )
        if advisor.admin_role == "ADVISOR":
            query = query.filter(UserAccount.advisor_admin_id == advisor.id)
        else:
            query = query.filter(UserAccount.school_name == advisor.school_name)
        rows = query.order_by(RiskCase.created_at.desc()).limit(100).all()
        return [{"caseId": case.id, "studentUid": student.public_uid,
                 "riskLevel": case.risk_level, "status": case.status,
                 "action": "请按学校危机流程尽快联系学生；不可查看聊天内容。",
                 "createdAt": case.created_at} for case, _, student in rows]
