from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
import uuid

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.security import hash_password
from app.models.entities import CampusClass, UserAccount
from app.services.knowledge import KnowledgeService


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_user_identity_columns()
    _migrate_roster_columns()


def _migrate_user_identity_columns() -> None:
    """Add identity columns for installations created before organization support."""
    inspector = inspect(engine)
    existing = {column["name"] for column in inspector.get_columns("user_accounts")}
    additions = {
        "public_uid": "VARCHAR(32)",
        "student_number": "VARCHAR(32)",
        "identity_verified": "BOOLEAN DEFAULT 0",
        "admin_scope": "VARCHAR(16) DEFAULT 'NONE'",
        "school_name": "VARCHAR(128) DEFAULT ''",
        "college_name": "VARCHAR(128) DEFAULT ''",
        "account_status": "VARCHAR(24) DEFAULT 'ACTIVE'",
        "admin_role": "VARCHAR(32) DEFAULT 'NONE'",
        "admin_verification_status": "VARCHAR(24) DEFAULT 'NOT_REQUIRED'",
        "admin_employee_number": "VARCHAR(64)",
        "admin_verified_by": "INTEGER",
        "admin_verified_at": "DATETIME",
        "advisor_admin_id": "INTEGER",
    }
    missing = [(name, ddl) for name, ddl in additions.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(text(f"ALTER TABLE user_accounts ADD COLUMN {name} {ddl}"))


def _migrate_roster_columns() -> None:
    """Keep local databases created by earlier roster iterations compatible."""
    inspector = inspect(engine)
    if "staff_rosters" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("staff_rosters")}
    if "username" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE staff_rosters ADD COLUMN username VARCHAR(64)"))


def seed_data(db: Session) -> None:
    if db.query(UserAccount).count() == 0:
        admin = UserAccount(
            username="admin",
            display_name="Counselor Admin",
            password_hash=hash_password("admin123"),
            public_uid="ADM-DEMO-001",
            admin_scope="SCHOOL",
            school_name="演示大学",
            admin_role="SYSTEM_ADMIN",
            admin_verification_status="VERIFIED",
            admin_employee_number="SYS-DEMO-001",
        )
        admin.roles = {"ROLE_ADMIN", "ROLE_USER"}
        student = UserAccount(
            username="student",
            display_name="Demo Student",
            password_hash=hash_password("student123"),
            public_uid="STU-DEMO-001",
            school_name="演示大学",
            college_name="计算机学院",
        )
        student.roles = {"ROLE_USER"}
        db.add_all([admin, student])
        db.commit()

    demo = db.query(UserAccount).filter(UserAccount.username == "demo_admin").first()
    if demo is None:
        demo = UserAccount(
            username="demo_admin", display_name="全权限演示管理员",
            password_hash=hash_password("demo12345"), public_uid="ADM-DEMO-FULL",
            admin_scope="SCHOOL", school_name="演示大学", college_name="计算机学院",
            admin_role="DEMO_ADMIN", admin_verification_status="VERIFIED",
            admin_employee_number="DEMO-ADMIN-001", identity_verified=True,
        )
        demo.roles = {"ROLE_ADMIN", "ROLE_USER"}
        db.add(demo)
        db.commit()

    # Backfill identities for accounts created by older versions.
    for user in db.query(UserAccount).all():
        if not user.public_uid:
            prefix = "ADM" if "ROLE_ADMIN" in user.roles else "STU"
            user.public_uid = f"{prefix}-{uuid.uuid4().hex[:12].upper()}"
        # Never infer privileged scope or organization for legacy administrators.
        if "ROLE_ADMIN" not in user.roles and not user.school_name:
            user.school_name = "演示大学"
        if "ROLE_ADMIN" not in user.roles and not user.college_name:
            user.college_name = "计算机学院"
        if user.username == "student" and "ROLE_ADMIN" not in user.roles:
            user.identity_verified = True
        if user.username == "admin" and "ROLE_ADMIN" in user.roles:
            user.admin_role = "SYSTEM_ADMIN"
            user.admin_verification_status = "VERIFIED"
            user.admin_employee_number = user.admin_employee_number or "SYS-DEMO-001"
        elif "ROLE_ADMIN" in user.roles and user.admin_verification_status in {None, "", "NOT_REQUIRED"}:
            user.admin_verification_status = "UNVERIFIED"
    db.commit()

    service = KnowledgeService(db, get_settings())
    root = Path(__file__).resolve().parents[1]
    for file in sorted((root / "knowledge").glob("*.md")):
        service.ensure_source(file.name, file.read_text(encoding="utf-8"))
