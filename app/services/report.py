from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.entities import AlertRecord, AgentRunTrace, CaseIdentityAccess, CaseNote, ChatMessage, ChatSession, DeadLetterRecord, ExcelRecord, PsychologicalReport, RiskCase, ToolAuditRecord, ToolJob, UserAccount
from app.services.case_identity import CaseIdentityService
from app.schemas.dtos import AgentRunTraceResponse, CaseNoteResponse, ConversationMessageResponse, ConversationResponse, ConversationSummaryResponse, DeadLetterResponse, ReportResponse, RiskCaseResponse, ToolAuditResponse, ToolJobResponse, ToolRecordResponse


class ReportService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _scope(query, admin: UserAccount | None):
        # Query must already include psychological_reports (the ownership anchor).
        if admin is None:
            return query
        if not CaseIdentityService.valid_scope(admin):
            return query.filter(False)
        query = query.join(UserAccount, UserAccount.id == PsychologicalReport.user_id).filter(
            UserAccount.school_name == admin.school_name)
        if admin.admin_scope == "COLLEGE":
            query = query.filter(UserAccount.college_name == admin.college_name)
        return query

    def latest_reports(self, user_id: int | None = None, redact_sensitive: bool = False,
                       admin: UserAccount | None = None) -> list[ReportResponse]:
        query = self.db.query(PsychologicalReport).order_by(PsychologicalReport.created_at.desc())
        if user_id is not None:
            query = query.filter(PsychologicalReport.user_id == user_id)
        if admin is not None:
            if admin.admin_role not in {"COUNSELOR", "DEMO_ADMIN"}:
                return []
            # LOW/MEDIUM contribute only to aggregate statistics and never appear as persons.
            query = query.filter(PsychologicalReport.risk_level == "HIGH")
        return [self._report_response(item, redact_sensitive) for item in self._scope(query, admin).limit(100).all()]

    def excel_records(self, admin: UserAccount | None = None) -> list[ToolRecordResponse]:
        query = self.db.query(ExcelRecord).join(PsychologicalReport, PsychologicalReport.id == ExcelRecord.report_id)
        rows = self._scope(query, admin).order_by(ExcelRecord.created_at.desc()).limit(100).all()
        return [
            ToolRecordResponse(id=row.id, reportId=row.report_id, status=row.status, message=row.message, createdAt=row.created_at, filePath=row.file_path)
            for row in rows
        ]

    def alert_records(self, admin: UserAccount | None = None) -> list[ToolRecordResponse]:
        query = self.db.query(AlertRecord).join(PsychologicalReport, PsychologicalReport.id == AlertRecord.report_id)
        rows = self._scope(query, admin).order_by(AlertRecord.created_at.desc()).limit(100).all()
        return [
            ToolRecordResponse(
                id=row.id,
                reportId=row.report_id,
                status=row.status,
                message=row.message,
                createdAt=row.created_at,
                channel=row.channel,
                recipient=row.recipient,
            )
            for row in rows
        ]

    def risk_cases(self, admin: UserAccount | None = None) -> list[RiskCaseResponse]:
        access = CaseIdentityService(self.db)
        if admin is not None and not access.valid_scope(admin):
            return []
        query = self.db.query(RiskCase).join(PsychologicalReport, PsychologicalReport.id == RiskCase.report_id)
        query = query.filter(RiskCase.risk_level == "HIGH")
        if admin is not None:
            query = query.join(UserAccount, UserAccount.id == PsychologicalReport.user_id)
            if admin.admin_scope == "COLLEGE":
                query = query.filter(
                    UserAccount.school_name == admin.school_name,
                    UserAccount.college_name == admin.college_name,
                )
            elif admin.admin_scope == "SCHOOL":
                query = query.filter(UserAccount.school_name == admin.school_name)
        rows = query.order_by(RiskCase.updated_at.desc()).limit(100).all()
        bindings = {binding.case_id: binding for binding in self.db.query(CaseIdentityAccess).filter(
            CaseIdentityAccess.case_id.in_([row.id for row in rows])).all()} if rows else {}
        return [
            RiskCaseResponse(
                id=row.id,
                reportId=row.report_id,
                riskLevel=row.risk_level,
                status=row.status,
                owner=row.owner,
                summary=("高风险事件，已进入人工跟进流程。" if row.risk_level == "HIGH" else "已创建风险跟进个案，具体咨询内容受隐私保护。"),
                handoffSummary="仅展示必要的风险处置摘要，原始咨询内容不对管理员开放。",
                acknowledgedBy=row.acknowledged_by,
                acknowledgedAt=row.acknowledged_at,
                createdAt=row.created_at,
                updatedAt=row.updated_at,
                canClaim=bool(admin and row.id not in bindings and row.status != "CLOSED"),
                canHandle=bool(admin and row.id in bindings and bindings[row.id].admin_id == admin.id),
                contactConsent=(
                    "NOT_REQUIRED" if row.risk_level == "HIGH" else access.consent_state(bindings.get(row.id))
                ) if admin and row.id in bindings and bindings[row.id].admin_id == admin.id else "NOT_REQUESTED",
            )
            for row in rows
        ]

    def case_notes(self, case_id: int) -> list[CaseNoteResponse]:
        rows = self.db.query(CaseNote).filter(CaseNote.case_id == case_id).order_by(CaseNote.created_at.asc()).all()
        return [
            CaseNoteResponse(id=row.id, caseId=row.case_id, actor=row.actor, note=row.note, createdAt=row.created_at)
            for row in rows
        ]

    def tool_jobs(self, admin: UserAccount | None = None) -> list[ToolJobResponse]:
        query = self.db.query(ToolJob).join(PsychologicalReport, PsychologicalReport.id == ToolJob.report_id)
        rows = self._scope(query, admin).order_by(ToolJob.created_at.desc()).limit(100).all()
        return [
            ToolJobResponse(
                id=row.id,
                reportId=row.report_id,
                kind=row.kind,
                status=row.status,
                attempts=row.attempts,
                maxAttempts=row.max_attempts,
                dependsOnJobId=row.depends_on_job_id,
                runAfter=row.run_after,
                lastError=row.last_error,
                createdAt=row.created_at,
                updatedAt=row.updated_at,
            )
            for row in rows
        ]

    def dead_letters(self, admin: UserAccount | None = None) -> list[DeadLetterResponse]:
        query = self.db.query(DeadLetterRecord).join(PsychologicalReport, PsychologicalReport.id == DeadLetterRecord.report_id)
        rows = self._scope(query, admin).order_by(DeadLetterRecord.created_at.desc()).limit(100).all()
        return [
            DeadLetterResponse(
                id=row.id,
                jobId=row.job_id,
                reportId=row.report_id,
                kind=row.kind,
                reason=row.reason,
                payload=row.payload,
                createdAt=row.created_at,
            )
            for row in rows
        ]


    def agent_run_traces(self, redact_sensitive: bool = True, admin: UserAccount | None = None) -> list[AgentRunTraceResponse]:
        query = self.db.query(AgentRunTrace)
        if admin is not None:
            query = self._scope(query.join(PsychologicalReport, PsychologicalReport.id == AgentRunTrace.report_id), admin)
        rows = query.order_by(AgentRunTrace.created_at.desc()).limit(100).all()
        responses = []
        for row in rows:
            user = self.db.get(UserAccount, row.user_id)
            session = self.db.get(ChatSession, row.session_id)
            responses.append(
                AgentRunTraceResponse(
                    id=row.id,
                    sessionId=session.public_id if session else "",
                    reportId=row.report_id,
                    username=("匿名学生" if redact_sensitive else user.username if user else ""),
                    intent=row.intent,
                    riskLevel=row.risk_level,
                    originalInput=("[隐私保护]" if redact_sensitive else row.original_input),
                    sanitizedInput=("[隐私保护]" if redact_sensitive else row.sanitized_input),
                    memoryBrief=("[隐私保护]" if redact_sensitive else row.memory_brief),
                    agentSteps=(self._safe_trace_steps(_loads(row.agent_steps_json, [])) if redact_sensitive else _loads(row.agent_steps_json, [])),
                    retrievedKnowledge=_loads(row.retrieved_knowledge_json, []),
                    responseMessages=([] if redact_sensitive else _loads(row.response_messages_json, [])),
                    assessment=self._safe_assessment(_loads(row.assessment_json, {})) if redact_sensitive else _loads(row.assessment_json, {}),
                    createdAt=row.created_at,
                )
            )
        return responses

    @staticmethod
    def _safe_trace_steps(steps: list) -> list:
        return [
            {key: item.get(key) for key in ("kind", "type", "actor", "taskId", "artifactKind", "confidence") if key in item}
            for item in steps if isinstance(item, dict)
        ]

    @staticmethod
    def _safe_assessment(value: dict) -> dict:
        return {key: value.get(key) for key in ("risk", "emotion", "emotionScore", "confidence") if key in value}

    def tool_audits(self, admin: UserAccount | None = None) -> list[ToolAuditResponse]:
        query = self.db.query(ToolAuditRecord).join(PsychologicalReport, PsychologicalReport.id == ToolAuditRecord.report_id)
        rows = self._scope(query, admin).order_by(ToolAuditRecord.created_at.desc()).limit(100).all()
        return [
            ToolAuditResponse(
                id=row.id,
                jobId=row.job_id,
                reportId=row.report_id,
                toolName=row.tool_name,
                policy=row.policy,
                allowed=row.allowed,
                status=row.status,
                reason=row.reason,
                payload=_loads(row.payload, {}),
                createdAt=row.created_at,
                updatedAt=row.updated_at,
            )
            for row in rows
        ]

    def conversations(self, user_id: int, limit: int = 30) -> list[ConversationSummaryResponse]:
        rows = (
            self.db.query(ChatSession, func.count(ChatMessage.id))
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .filter(ChatSession.user_id == user_id)
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [
            ConversationSummaryResponse(
                sessionId=session.public_id,
                title=session.title,
                messageCount=message_count,
                createdAt=session.created_at,
                updatedAt=session.updated_at,
            )
            for session, message_count in rows
        ]

    def conversation(self, public_id: str, redact_sensitive: bool = True, user_id: int | None = None,
                     admin: UserAccount | None = None) -> ConversationResponse:
        query = self.db.query(ChatSession).filter(ChatSession.public_id == public_id)
        if user_id is not None:
            query = query.filter(ChatSession.user_id == user_id)
        if admin is not None:
            if not CaseIdentityService.valid_scope(admin):
                query = query.filter(False)
            query = query.join(UserAccount, UserAccount.id == ChatSession.user_id).filter(
                UserAccount.school_name == admin.school_name)
            if admin.admin_scope == "COLLEGE":
                query = query.filter(UserAccount.college_name == admin.college_name)
        session = query.first()
        if session is None:
            raise ValueError("Session not found")
        rows = self.db.query(ChatMessage).filter(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc()).all()
        return ConversationResponse(
            sessionId=session.public_id,
            title="[隐私保护] 学生会话" if redact_sensitive else session.title,
            messages=[ConversationMessageResponse(
                role=row.role,
                content=("[隐私保护] 原始咨询内容仅学生本人可见。" if redact_sensitive else row.content),
                createdAt=row.created_at,
            ) for row in rows],
        )

    def _report_response(self, report: PsychologicalReport, redact_sensitive: bool = False) -> ReportResponse:
        user = self.db.get(UserAccount, report.user_id)
        session = self.db.get(ChatSession, report.session_id)
        return ReportResponse(
            id=report.id,
            sessionId=session.public_id if session else "",
            username=("匿名学生" if redact_sensitive else user.username if user else ""),
            displayName=("匿名学生" if redact_sensitive else user.display_name if user else ""),
            content=("[隐私保护] 原始咨询内容仅学生本人可见。" if redact_sensitive else report.content),
            intent=report.intent,
            emotion=report.emotion,
            emotionScore=report.emotion_score,
            riskLevel=report.risk_level,
            confidence=report.confidence,
            summary=(
                "高风险事件，已进入人工跟进流程。" if redact_sensitive and report.risk_level == "HIGH"
                else "已完成风险评估，具体咨询内容不在管理员列表展示。" if redact_sensitive
                else report.summary
            ),
            createdAt=report.created_at,
        )


def _loads(raw: str, default):
    import json

    try:
        return json.loads(raw or "")
    except Exception:
        return default
