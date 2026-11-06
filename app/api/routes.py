from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.factory import agent_framework_status
from app.agents.event_driven_runtime import EventDrivenAgentRuntimeService
from app.core.config import get_settings
from app.core.database import get_db
import base64

from app.core.security import (current_user, hash_password, require_counselor,
                               require_system_admin, require_verified_admin, verify_password)
from app.core.health import readiness_report
from app.core.request_context import get_request_id
from app.models.entities import CaseIdentityAccess, PsychologicalReport, RiskCase, UserAccount
from app.services.case_identity import ACTIVE_STATUSES, CaseAccessError, CaseIdentityService
from app.services.admin_access import AdminAccessError, AdminAccessService
from app.services.organization import OrganizationError, OrganizationService, new_uid
from app.services.roster import RosterImportError, RosterService
from app.schemas.dtos import (
    CaseAcknowledgeRequest, CaseConsentRequest,
    CaseIdentityRequest, CaseIdentityResponse,
    CaseNoteCreateRequest, CaseStatusUpdateRequest,
    ChatRequest, ClassApplyRequest, ClassCreateRequest, ClassInviteRequest, ClassLeaveRequest, ClassReviewRequest,
    KnowledgeIngestRequest, KnowledgeIngestResponse, LoginRequest, RegisterRequest, StudentIdentityRequest, authority,
)
from app.services.chat import ChatService
from app.services.knowledge import KnowledgeService
from app.services.model_assets import finetuned_model_status
from app.services.report import ReportService
from app.services.skills import MindBridgeSkillLibrary
from app.services.tools import ToolOrchestrationService

router = APIRouter()


@router.get("/actuator/health")
def health():
    return {"status": "UP", "service": "mindbridge", "requestId": get_request_id()}


def _profile_payload(user: UserAccount) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "publicUid": user.public_uid,
        "studentNumber": user.student_number,
        "identityVerified": bool(user.identity_verified) if "ROLE_ADMIN" not in user.roles else True,
        "adminScope": user.admin_scope,
        "schoolName": user.school_name,
        "collegeName": user.college_name,
        "adminRole": user.admin_role,
        "adminVerificationStatus": user.admin_verification_status,
        "employeeNumber": user.admin_employee_number,
        "roles": [authority(role) for role in user.roles],
    }


@router.post("/api/auth/register", status_code=201)
def register(request: RegisterRequest, db: Annotated[Session, Depends(get_db)]):
    if db.query(UserAccount).filter(UserAccount.username == request.username).first() is not None:
        raise HTTPException(409, "手机号已注册，请直接登录")
    if request.accountType == "admin":
        if not request.employeeNumber.strip():
            raise HTTPException(422, "辅导员账号必须填写学校名册中的工号")
    elif not request.studentNumber.strip():
        raise HTTPException(422, "学生注册必须填写学号")
    elif db.query(UserAccount).filter(UserAccount.student_number == request.studentNumber.strip()).first() is not None:
        raise HTTPException(409, "学号已存在，请核对后重试")
    user = UserAccount(
        username=request.username,
        display_name=request.displayName.strip(),
        student_number=request.studentNumber.strip() if request.accountType == "student" else None,
        identity_verified=False,
        password_hash=hash_password(request.password),
        public_uid=new_uid("ADM" if request.accountType == "admin" else "STU"),
        admin_scope="COLLEGE" if request.accountType == "admin" else "NONE",
        admin_role="NONE",
        admin_verification_status="UNVERIFIED" if request.accountType == "admin" else "NOT_REQUIRED",
        admin_employee_number=request.employeeNumber.strip() or None,
        school_name="" if request.accountType == "admin" else request.schoolName.strip(),
        college_name="" if request.accountType == "admin" else request.collegeName.strip(),
    )
    user.roles = {"ROLE_USER", "ROLE_ADMIN"} if request.accountType == "admin" else {"ROLE_USER"}
    db.add(user)
    try:
        db.flush()
        roster = RosterService(db)
        if request.accountType == "admin" and not roster.activate_staff_registration(user):
            raise RosterImportError("学校辅导员名册中未找到该工号，请联系学校管理员先导入名单")
        roster_matched = request.accountType == "student" and roster.activate_registration(user)
        db.commit()
    except RosterImportError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.refresh(user)
    token = base64.b64encode(f"{user.username}:{request.password}".encode()).decode()
    return {"token": token, "profile": _profile_payload(user),
            "message": "辅导员账号已按学校名册自动开通" if request.accountType == "admin"
            else ("注册成功，已匹配学校名册" if roster_matched else "注册成功，等待学校导入名册后完成认证")}


@router.post("/api/auth/login")
def login(request: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.query(UserAccount).filter(UserAccount.username == request.username).first()
    if user is None:
        raise HTTPException(404, "账号不存在，请先注册")
    if user.account_status != "ACTIVE" or not verify_password(request.password, user.password_hash):
        raise HTTPException(401, "密码错误或账号已停用")
    token = base64.b64encode(f"{user.username}:{request.password}".encode()).decode()
    return {"token": token, "profile": _profile_payload(user)}


@router.get("/actuator/readiness")
def readiness(db: Annotated[Session, Depends(get_db)]):
    report = readiness_report(db, get_settings())
    report["requestId"] = get_request_id()
    return report


@router.get("/api/profile")
def profile(user: Annotated[UserAccount, Depends(current_user)]):
    return _profile_payload(user)


def _admin_access_error(exc: AdminAccessError):
    return HTTPException(exc.status_code, str(exc))


@router.get("/api/admin/advisor-alerts")
def advisor_alerts(admin: Annotated[UserAccount, Depends(require_verified_admin)],
                   db: Annotated[Session, Depends(get_db)]):
    try:
        return AdminAccessService(db).advisor_alerts(admin)
    except AdminAccessError as exc:
        raise _admin_access_error(exc) from exc


@router.post("/api/admin/roster/import")
async def import_student_roster(
    file: Annotated[UploadFile, File(...)],
    admin: Annotated[UserAccount, Depends(require_verified_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "请上传 CSV 格式的学生名单")
    try:
        return RosterService(db).import_csv(admin, await file.read())
    except RosterImportError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/profile/identity")
def verify_student_identity(
    request: StudentIdentityRequest,
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if "ROLE_ADMIN" in user.roles:
        raise HTTPException(403, "管理员账号不需要学生实名认证")
    student_number = request.studentNumber.strip()
    existing = db.query(UserAccount).filter(
        UserAccount.student_number == student_number,
        UserAccount.id != user.id,
    ).first()
    if existing is not None:
        raise HTTPException(409, "学号已被其他账号认证")
    user.student_number = student_number
    user.display_name = request.realName.strip()
    db.add(user)
    try:
        if not RosterService(db).activate_registration(user):
            raise HTTPException(409, "学校名册中未找到该学号，请联系学校或辅导员导入名单")
        db.commit()
    except RosterImportError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.refresh(user)
    return _profile_payload(user)


@router.get("/api/classes/search")
def search_classes(
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    query: str = "",
):
    try:
        return OrganizationService(db).search_classes(user, query)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/api/classes/mine")
def my_classes(
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).mine(user)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/api/classes/apply")
def apply_class(
    request: ClassApplyRequest,
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).apply(user, request.classUid)
    except OrganizationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/classes/leave")
def leave_class(
    request: ClassLeaveRequest,
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).leave(user, request.classUid)
    except OrganizationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/admin/classes", status_code=201)
def create_class(
    request: ClassCreateRequest,
    user: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).create_class(user, request.name, request.schoolName, request.collegeName)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/api/admin/classes")
def admin_classes(
    user: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).classes_for_admin(user)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/api/admin/class-applications")
def class_applications(
    user: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
    status: str = "PENDING",
):
    try:
        return OrganizationService(db).applications(user, status)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/api/admin/class-applications/{membership_id}/review")
def review_class_application(
    membership_id: int,
    request: ClassReviewRequest,
    user: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).review(user, membership_id, request.decision, request.note)
    except OrganizationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/admin/students/search")
def search_students(
    user: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
    query: str = "",
):
    try:
        return OrganizationService(db).search_students(user, query)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/api/admin/classes/{class_uid}/invite")
def invite_students(
    class_uid: str,
    request: ClassInviteRequest,
    user: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return OrganizationService(db).invite(user, class_uid, request.studentUids)
    except OrganizationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if "ROLE_ADMIN" in user.roles:
        raise HTTPException(403, "管理员账号只能查看后台记录，不能发起学生对话。")
    service = ChatService(db, get_settings())
    return StreamingResponse(service.stream_chat(user, request), media_type="text/event-stream")


@router.get("/api/conversations")
def my_conversations(
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 30,
):
    if "ROLE_ADMIN" in user.roles:
        raise HTTPException(403, "管理员账号不能读取学生个人会话列表。")
    return ReportService(db).conversations(user.id, limit)


@router.get("/api/conversations/{session_id}")
def my_conversation(
    session_id: str,
    user: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if "ROLE_ADMIN" in user.roles:
        raise HTTPException(403, "管理员账号不能读取学生个人会话。")
    try:
        return ReportService(db).conversation(session_id, redact_sensitive=False, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(404, "会话不存在") from exc


@router.get("/api/agent/status")
def agent_status(user: Annotated[UserAccount, Depends(current_user)]):
    settings = get_settings()
    provider = settings.ai_provider.lower()
    model = settings.ollama_model if provider == "ollama" else settings.openai_model if provider == "openai" else "mock"
    framework = agent_framework_status(settings)
    return {
        "provider": provider,
        "model": model,
        "realModelEnabled": provider in {"ollama", "openai"},
        "agentFramework": framework,
        "finetunedModel": finetuned_model_status(settings),
        "agents": [
            {"name": "CoordinatorAgent", "status": "READY", "description": "维护任务板、预算、安全门槛、冲突仲裁和最终采纳"},
            {"name": "UnderstandingAgent", "status": "READY", "description": "独立理解用户输入，发布 intent artifact"},
            {"name": "SafetyAgent", "status": "READY", "description": "独立风险评估、SAFETY_OVERRIDE 和候选回复安全审查"},
            {"name": "ContextAgent", "status": "READY", "description": "独立记忆视图、RAG 检索和 skill 上下文聚合"},
            {"name": "ResponseAgent", "status": "READY", "description": "根据黑板 artifact 发布候选回复方案"},
        ],
        "skills": MindBridgeSkillLibrary.status_items(),
        "runtimeHarness": {
            "name": "MindBridgeAgentHarness",
            "status": "READY",
            "description": "统一管理单轮 Agent run 的输入脱敏、上下文注入、风险报告、工具计划和 trace 输出",
            "policy": {
                "maxInputChars": settings.agent_max_input_chars,
                "maxOutputChars": settings.agent_max_output_chars,
                "maxSteps": settings.agent_max_steps,
                "timeoutSeconds": settings.agent_timeout_seconds,
                "toolAuthorization": "deny-by-default",
            },
            "observability": {
                "requestId": "X-Request-ID",
                "tracePersistence": "agent_run_traces",
                "replayableState": "append-only-blackboard",
            },
        },
        "loop": {
            "type": "event-driven-multi-agent",
            "maxSteps": EventDrivenAgentRuntimeService.max_steps,
            "scheduler": "claim-based-actor-runtime",
        },
        "collaboration": {
            "scheduler": "claim-based",
            "state": "append-only-blackboard",
            "messageBus": "per-agent inbox over shared mailbox",
            "fixedWorkflow": False,
            "agentIsolation": {
                "prompt": "per-agent system prompt",
                "memory": "per-agent private Redis key",
                "model": "per-agent model profile",
                "tools": "per-agent tool permissions",
            },
        },
    }


@router.get("/api/reports/me")
def my_reports(user: Annotated[UserAccount, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).latest_reports(user.id)


@router.get("/api/admin/reports")
def admin_reports(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).latest_reports(redact_sensitive=True, admin=admin)


@router.get("/api/admin/risk-statistics")
def risk_statistics(admin: Annotated[UserAccount, Depends(require_counselor)],
                    db: Annotated[Session, Depends(get_db)]):
    query = db.query(PsychologicalReport.risk_level, UserAccount.college_name, func.count(PsychologicalReport.id)).join(
        UserAccount, UserAccount.id == PsychologicalReport.user_id).filter(
            UserAccount.school_name == admin.school_name)
    if admin.admin_scope == "COLLEGE":
        query = query.filter(UserAccount.college_name == admin.college_name)
    rows = query.group_by(PsychologicalReport.risk_level, UserAccount.college_name).all()
    totals = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    colleges = {}
    for risk, college, count in rows:
        totals[risk] = totals.get(risk, 0) + count
        colleges.setdefault(college or "未填写学院", {"LOW": 0, "MEDIUM": 0, "HIGH": 0})[risk] = count
    return {"totals": totals, "colleges": [{"collegeName": name, **counts} for name, counts in colleges.items()]}


@router.get("/api/admin/excel-records")
def admin_excel(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).excel_records(admin)


@router.get("/api/admin/alerts")
def admin_alerts(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).alert_records(admin)


@router.get("/api/admin/cases")
def admin_cases(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).risk_cases(admin)


def _require_case_access(db: Session, admin: UserAccount, case_id: int) -> RiskCase:
    try:
        return CaseIdentityService(db).scoped_case(admin, case_id)[0]
    except CaseAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _require_case_handler(db: Session, admin: UserAccount, case_id: int, *, allow_closed: bool = False):
    try:
        return CaseIdentityService(db).require_handler(admin, case_id, allow_closed=allow_closed)
    except CaseAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/api/admin/cases/{case_id}/identity", response_model=CaseIdentityResponse)
def admin_case_identity(
    case_id: int, request: CaseIdentityRequest, response: Response,
    admin: Annotated[UserAccount, Depends(require_counselor)],
    db: Annotated[Session, Depends(get_db)],
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseIdentityService(db).reveal(admin, case_id, request.reason, request.emergencyConfirmed)
    except CaseAccessError as exc:
        raise HTTPException(exc.status_code, str(exc), headers={"Cache-Control": "no-store"}) from exc


@router.get("/api/admin/cases/{case_id}/identity-audits")
def admin_identity_audits(
    case_id: int, response: Response,
    admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)],
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseIdentityService(db).audits(admin, case_id)
    except CaseAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/api/risk-contact-requests")
def student_contact_requests(
    response: Response, student: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseIdentityService(db).student_requests(student)
    except CaseAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/api/risk-contact-requests/{case_id}/consent")
def student_contact_consent(
    case_id: int, request: CaseConsentRequest, response: Response,
    student: Annotated[UserAccount, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseIdentityService(db).set_consent(student, case_id, request.decision)
    except CaseAccessError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/api/risk-contact-requests/{case_id}/identity-audits")
def student_identity_audits(
    case_id: int, response: Response, student: Annotated[UserAccount, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseIdentityService(db).student_audits(student, case_id)
    except CaseAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/api/admin/cases/{case_id}/notes")
def admin_case_notes(case_id: int, admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    _require_case_handler(db, admin, case_id, allow_closed=True)
    return ReportService(db).case_notes(case_id)


@router.post("/api/admin/cases/{case_id}/acknowledge")
def acknowledge_admin_case(
    case_id: int,
    request: CaseAcknowledgeRequest,
    admin: Annotated[UserAccount, Depends(require_counselor)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        existing = db.get(CaseIdentityAccess, case_id)
        case = CaseIdentityService(db).claim(admin, case_id)
        if existing and case.status in ACTIVE_STATUSES:
            return {"id": case.id, "status": case.status}
        case = ToolOrchestrationService(db, get_settings()).acknowledge_case(
            case_id, admin.display_name or admin.username, request.note
        )
        return {"id": case.id, "status": case.status}
    except CaseAccessError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/admin/cases/{case_id}/notes", status_code=201)
def add_admin_case_note(
    case_id: int,
    request: CaseNoteCreateRequest,
    admin: Annotated[UserAccount, Depends(require_counselor)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_case_handler(db, admin, case_id)
    try:
        return ToolOrchestrationService(db, get_settings()).add_case_note(
            case_id, admin.display_name or admin.username, request.note
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/admin/cases/{case_id}/status")
def update_admin_case_status(
    case_id: int,
    request: CaseStatusUpdateRequest,
    admin: Annotated[UserAccount, Depends(require_counselor)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_case_handler(db, admin, case_id)
    try:
        case = ToolOrchestrationService(db, get_settings()).update_case_status(
            case_id, admin.display_name or admin.username, request.status, request.note
        )
        return {"id": case.id, "status": case.status}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/admin/tool-jobs")
def admin_tool_jobs(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).tool_jobs(admin)


@router.get("/api/admin/dead-letters")
def admin_dead_letters(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).dead_letters(admin)


@router.get("/api/admin/agent-traces")
def admin_agent_traces(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).agent_run_traces(redact_sensitive=True, admin=admin)


@router.get("/api/admin/tool-audits")
def admin_tool_audits(admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    return ReportService(db).tool_audits(admin)


@router.get("/api/admin/conversations/{session_id}")
def admin_conversation(session_id: str, admin: Annotated[UserAccount, Depends(require_counselor)], db: Annotated[Session, Depends(get_db)]):
    try:
        return ReportService(db).conversation(session_id, redact_sensitive=True, admin=admin)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/api/admin/knowledge")
def ingest_knowledge(
    request: KnowledgeIngestRequest,
    _: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    chunks = KnowledgeService(db, get_settings()).ingest(request.source, request.content)
    return KnowledgeIngestResponse(source=request.source, chunks=chunks)


@router.get("/api/admin/knowledge/status")
def knowledge_status(_: Annotated[UserAccount, Depends(require_system_admin)], db: Annotated[Session, Depends(get_db)]):
    return KnowledgeService(db, get_settings()).status()


@router.post("/api/admin/knowledge/rebuild-vector")
def rebuild_knowledge_vector(_: Annotated[UserAccount, Depends(require_system_admin)], db: Annotated[Session, Depends(get_db)]):
    try:
        indexed = KnowledgeService(db, get_settings()).rebuild_vector_index()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"indexedChunks": indexed}


@router.post("/api/admin/knowledge/backup")
def backup_knowledge_vector(_: Annotated[UserAccount, Depends(require_system_admin)], db: Annotated[Session, Depends(get_db)]):
    try:
        snapshot = KnowledgeService(db, get_settings()).backup_vector_index()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"snapshot": snapshot}


@router.post("/api/admin/knowledge/file")
async def ingest_file(
    _: Annotated[UserAccount, Depends(require_system_admin)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    chunks = KnowledgeService(db, get_settings()).ingest_file(file.filename or "uploaded-file", await file.read())
    return KnowledgeIngestResponse(source=file.filename or "uploaded-file", chunks=chunks)
