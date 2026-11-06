from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    sessionId: Optional[str] = None


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=1, max_length=128)
    studentNumber: str = Field(default="", max_length=32, pattern=r"^[A-Za-z0-9-]*$")
    accountType: str = Field(default="student", pattern=r"^(student|admin)$")
    adminScope: str = Field(default="NONE", pattern=r"^(NONE|COLLEGE|SCHOOL)$")
    schoolName: str = Field(default="", max_length=128)
    collegeName: str = Field(default="", max_length=128)
    adminRole: str = Field(default="COUNSELOR", pattern=r"^(COUNSELOR|ADVISOR)$")
    employeeNumber: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9-]*$")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class StudentIdentityRequest(BaseModel):
    studentNumber: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9-]+$")
    realName: str = Field(min_length=2, max_length=128)


class ClassCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    schoolName: str = Field(default="", max_length=128)
    collegeName: str = Field(default="", max_length=128)


class ClassApplyRequest(BaseModel):
    classUid: str = Field(min_length=4, max_length=32)


class ClassLeaveRequest(BaseModel):
    classUid: str = Field(min_length=4, max_length=32)


class ClassReviewRequest(BaseModel):
    decision: str = Field(pattern=r"^(APPROVED|REJECTED)$")
    note: str = Field(default="", max_length=512)


class ClassInviteRequest(BaseModel):
    studentUids: list[str] = Field(min_length=1, max_length=500)


class ChatStreamEvent(BaseModel):
    sessionId: Optional[str] = None
    content: Optional[str] = None
    message: Optional[str] = None
    type: str


class KnowledgeIngestRequest(BaseModel):
    source: str
    content: str


class KnowledgeIngestResponse(BaseModel):
    source: str
    chunks: int


class ReportResponse(BaseModel):
    id: int
    sessionId: str
    username: str
    displayName: str
    content: str
    intent: str
    emotion: str
    emotionScore: float
    riskLevel: str
    confidence: float
    summary: str
    createdAt: datetime


class ConversationMessageResponse(BaseModel):
    role: str
    content: str
    createdAt: datetime


class ConversationSummaryResponse(BaseModel):
    sessionId: str
    title: str
    messageCount: int
    createdAt: datetime
    updatedAt: datetime


class ConversationResponse(BaseModel):
    sessionId: str
    title: str
    messages: list[ConversationMessageResponse]


class ToolRecordResponse(BaseModel):
    id: int
    reportId: int
    status: str
    message: str
    createdAt: datetime
    channel: Optional[str] = None
    recipient: Optional[str] = None
    filePath: Optional[str] = None


class RiskCaseResponse(BaseModel):
    id: int
    reportId: int
    riskLevel: str
    status: str
    owner: str
    summary: str
    handoffSummary: str
    acknowledgedBy: Optional[str] = None
    acknowledgedAt: Optional[datetime] = None
    createdAt: datetime
    updatedAt: datetime
    canClaim: bool = False
    canHandle: bool = False
    contactConsent: str = "NOT_REQUESTED"


class CaseNoteResponse(BaseModel):
    id: int
    caseId: int
    actor: str
    note: str
    createdAt: datetime


class CaseIdentityRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    emergencyConfirmed: bool = False


class CaseConsentRequest(BaseModel):
    decision: str = Field(pattern=r"^(GRANTED|DECLINED|REVOKED)$")


class CaseIdentityResponse(BaseModel):
    name: str
    studentNumber: Optional[str]
    studentUid: Optional[str]
    schoolName: str
    collegeName: str
    classes: list[str]
    identityStatus: str
    contactStatus: str
    basis: str


class CaseAcknowledgeRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class CaseNoteCreateRequest(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


class CaseStatusUpdateRequest(BaseModel):
    status: str = Field(pattern=r"^(REFERRED|CLOSED)$")
    note: str = Field(min_length=1, max_length=1000)


class ToolJobResponse(BaseModel):
    id: int
    reportId: int
    kind: str
    status: str
    attempts: int
    maxAttempts: int
    dependsOnJobId: Optional[int] = None
    runAfter: datetime
    lastError: str
    createdAt: datetime
    updatedAt: datetime


class DeadLetterResponse(BaseModel):
    id: int
    jobId: Optional[int] = None
    reportId: int
    kind: str
    reason: str
    payload: str
    createdAt: datetime


class AgentRunTraceResponse(BaseModel):
    id: int
    sessionId: str
    reportId: Optional[int] = None
    username: str
    intent: str
    riskLevel: str
    originalInput: str
    sanitizedInput: str
    memoryBrief: str
    agentSteps: list[dict[str, Any]]
    retrievedKnowledge: list[dict[str, Any]]
    responseMessages: list[dict[str, Any]]
    assessment: dict[str, Any]
    createdAt: datetime


class ToolAuditResponse(BaseModel):
    id: int
    jobId: Optional[int] = None
    reportId: Optional[int] = None
    toolName: str
    policy: str
    allowed: bool
    status: str
    reason: str
    payload: dict[str, Any]
    createdAt: datetime
    updatedAt: datetime


class AiMessage(BaseModel):
    role: str
    content: str


def authority(role: str) -> dict[str, Any]:
    return {"authority": role}
