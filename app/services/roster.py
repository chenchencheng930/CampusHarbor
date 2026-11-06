from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.entities import CampusClass, ClassMembership, StaffRoster, StudentRoster, UserAccount
from app.services.organization import new_uid


class RosterImportError(ValueError):
    pass


class RosterService:
    HEADERS = {
        "student_number": ("学号", "student_number", "studentNumber"),
        "display_name": ("姓名", "name", "display_name", "displayName"),
        "school_name": ("学校", "school", "school_name", "schoolName"),
        "college_name": ("学院", "college", "college_name", "collegeName"),
        "class_name": ("班级", "class", "class_name", "className"),
        "employee_number": ("工号", "employee_number", "employeeNumber"),
        "username": ("手机号", "账号", "username", "用户名", "phone"),
        "role": ("身份", "role", "角色"),
    }

    def __init__(self, db: Session):
        self.db = db

    def import_csv(self, admin: UserAccount, payload: bytes) -> dict:
        if admin.admin_role not in {"SYSTEM_ADMIN", "ADVISOR", "DEMO_ADMIN"}:
            raise RosterImportError("仅学校管理员或辅导员可以导入学生名单")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RosterImportError("名单必须是 UTF-8 编码的 CSV 文件") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise RosterImportError("CSV 缺少表头")
        rows = list(reader)
        if not rows:
            raise RosterImportError("CSV 中没有学生数据")
        if len(rows) > 5000:
            raise RosterImportError("单次最多导入 5000 名学生")

        result = {"total": len(rows), "created": 0, "updated": 0, "activated": 0,
                  "assigned": 0, "pendingAdvisor": 0, "staffCreated": 0,
                  "staffUpdated": 0, "staffActivated": 0, "errors": []}
        seen = set()
        for line, raw in enumerate(rows, 2):
            counters_before = {key: value for key, value in result.items()
                               if key != "errors"}
            savepoint = self.db.begin_nested()
            try:
                values = {key: self._value(raw, aliases) for key, aliases in self.HEADERS.items()}
                number, employee, name = values["student_number"], values["employee_number"], values["display_name"]
                school = values["school_name"] or admin.school_name
                college = values["college_name"] or admin.college_name
                class_name = values["class_name"]
                record_key = employee or number
                if not record_key:
                    raise RosterImportError("每行必须包含学号或工号")
                if record_key in seen:
                    raise RosterImportError("文件内学号或工号重复")
                seen.add(record_key)
                if employee:
                    created, activated, assigned = self._import_staff(admin, values, school, college)
                    result["staffCreated" if created else "staffUpdated"] += 1
                    result["staffActivated"] += int(activated)
                    result["assigned"] += assigned
                    self.db.flush()
                    savepoint.commit()
                    continue
                if not number or not name or not school or not college:
                    raise RosterImportError("学号、姓名、学校和学院不能为空")
                if admin.school_name and school != admin.school_name:
                    raise RosterImportError("不能导入其他学校的学生")
                if admin.admin_role == "ADVISOR" and college != admin.college_name:
                    raise RosterImportError("辅导员只能导入本人负责学院")
                advisor = self._advisor(school, college, admin)
                roster = self.db.query(StudentRoster).filter(StudentRoster.student_number == number).first()
                if roster and roster.school_name != school:
                    raise RosterImportError("学号已存在于其他学校名册")
                if roster is None:
                    roster = StudentRoster(student_number=number, display_name=name,
                                           school_name=school, college_name=college,
                                           imported_by=admin.id)
                    self.db.add(roster)
                    result["created"] += 1
                else:
                    result["updated"] += 1
                roster.display_name = name
                roster.college_name = college
                roster.class_name = class_name
                roster.advisor_admin_id = advisor.id if advisor else None
                roster.imported_by = admin.id
                roster.updated_at = datetime.utcnow()
                if advisor:
                    result["assigned"] += 1
                else:
                    result["pendingAdvisor"] += 1
                student = self.db.query(UserAccount).filter(UserAccount.student_number == number).first()
                if student and "ROLE_ADMIN" not in student.roles:
                    student.display_name = name
                    student.school_name = school
                    student.college_name = college
                    student.identity_verified = True
                    student.advisor_admin_id = advisor.id if advisor else None
                    self.db.flush()
                    roster.user_id = student.id
                    result["activated"] += 1
                    if class_name:
                        self._join_class(admin, student, school, college, class_name)
                self.db.flush()
                savepoint.commit()
            except (RosterImportError, ValueError, SQLAlchemyError) as exc:
                savepoint.rollback()
                for key, value in counters_before.items():
                    result[key] = value
                result["errors"].append({"line": line, "message": str(exc)})
        self.db.commit()
        result["success"] = (result["created"] + result["updated"]
                             + result["staffCreated"] + result["staffUpdated"])
        return result

    def _import_staff(self, admin: UserAccount, values: dict[str, str], school: str,
                      college: str) -> tuple[bool, bool, int]:
        if admin.admin_role not in {"SYSTEM_ADMIN", "DEMO_ADMIN"}:
            raise RosterImportError("只有学校管理员可以导入辅导员名单")
        employee, name, username = values["employee_number"], values["display_name"], values["username"]
        if not name or not school or not college:
            raise RosterImportError("辅导员名单必须包含工号、姓名、学校和学院")
        if admin.school_name and school != admin.school_name:
            raise RosterImportError("不能导入其他学校的辅导员")
        if admin.admin_role == "ADVISOR" and college != admin.college_name:
            raise RosterImportError("辅导员只能导入本人负责学院")
        role = (values["role"] or "ADVISOR").upper()
        if role not in {"ADVISOR", "COUNSELOR"}:
            raise RosterImportError("辅导员身份只能填写 ADVISOR 或 COUNSELOR")
        account = self.db.query(UserAccount).filter(UserAccount.admin_employee_number == employee).first()
        if account and (account.display_name.strip() != name.strip()
                        or (username and account.username != username)):
            raise RosterImportError("工号对应账号的姓名或用户名与导入名单不一致")
        row = self.db.query(StaffRoster).filter(StaffRoster.employee_number == employee).first()
        created = row is None
        if row is None:
            row = StaffRoster(employee_number=employee, username=username or None, display_name=name,
                              school_name=school, college_name=college,
                              role=role, imported_by=admin.id)
            self.db.add(row)
        else:
            row.display_name, row.school_name, row.college_name = name, school, college
            row.username = username or row.username
            row.role, row.imported_by, row.updated_at = role, admin.id, datetime.utcnow()
        if account:
            return created, True, self._activate_staff(account, row)
        return created, False, 0

    def _activate_staff(self, account: UserAccount, row: StaffRoster) -> int:
        account.display_name = row.display_name
        account.school_name = row.school_name
        account.college_name = row.college_name
        account.admin_role = row.role
        account.admin_scope = "COLLEGE"
        account.admin_verification_status = "VERIFIED"
        account.identity_verified = True
        account.roles = {"ROLE_ADMIN", "ROLE_USER"}
        row.user_id = account.id
        assigned = 0
        if row.role == "ADVISOR":
            self.db.query(UserAccount).filter(
                UserAccount.id != account.id, UserAccount.admin_role == "ADVISOR",
                UserAccount.admin_verification_status == "VERIFIED",
                UserAccount.school_name == row.school_name,
                UserAccount.college_name == row.college_name,
            ).update({UserAccount.admin_verification_status: "REJECTED"}, synchronize_session=False)
            assigned = self.db.query(UserAccount).filter(
                UserAccount.roles_csv.notlike("%ROLE_ADMIN%"),
                UserAccount.school_name == row.school_name,
                UserAccount.college_name == row.college_name,
            ).update({UserAccount.advisor_admin_id: account.id}, synchronize_session=False)
            self.db.query(StudentRoster).filter(
                StudentRoster.school_name == row.school_name,
                StudentRoster.college_name == row.college_name,
            ).update({StudentRoster.advisor_admin_id: account.id}, synchronize_session=False)
        return assigned

    def activate_registration(self, student: UserAccount) -> bool:
        roster = self.db.query(StudentRoster).filter(
            StudentRoster.student_number == student.student_number).first()
        if not roster:
            return False
        if roster.display_name.strip() != student.display_name.strip():
            raise RosterImportError("姓名与学校导入名册不一致，请联系学校管理员")
        student.school_name = roster.school_name
        student.college_name = roster.college_name
        student.advisor_admin_id = roster.advisor_admin_id
        student.identity_verified = True
        self.db.flush()
        roster.user_id = student.id
        roster.updated_at = datetime.utcnow()
        if roster.class_name:
            owner = self.db.get(UserAccount, roster.imported_by)
            self._join_class(owner or student, student, roster.school_name,
                             roster.college_name, roster.class_name)
        return True

    def activate_staff_registration(self, account: UserAccount) -> bool:
        if not account.admin_employee_number:
            return False
        row = self.db.query(StaffRoster).filter(
            StaffRoster.employee_number == account.admin_employee_number).first()
        if not row:
            return False
        if row.display_name.strip() != account.display_name.strip():
            raise RosterImportError("姓名与学校导入的辅导员名单不一致")
        if row.username and row.username != account.username:
            raise RosterImportError("账号与学校导入的辅导员名单不一致")
        self._activate_staff(account, row)
        return True

    @staticmethod
    def _value(row: dict, aliases: tuple[str, ...]) -> str:
        for alias in aliases:
            if alias in row and row[alias] is not None:
                return str(row[alias]).strip()
        return ""

    def _advisor(self, school: str, college: str, admin: UserAccount) -> UserAccount | None:
        if admin.admin_role == "ADVISOR":
            return admin
        return self.db.query(UserAccount).filter(
            UserAccount.admin_role == "ADVISOR",
            UserAccount.admin_verification_status == "VERIFIED",
            UserAccount.school_name == school,
            UserAccount.college_name == college,
        ).first()

    def _join_class(self, owner: UserAccount, student: UserAccount, school: str,
                    college: str, name: str) -> None:
        campus_class = self.db.query(CampusClass).filter(
            CampusClass.school_name == school, CampusClass.college_name == college,
            CampusClass.name == name, CampusClass.status == "ACTIVE").first()
        if campus_class is None:
            campus_class = CampusClass(public_uid=new_uid("CLS"), name=name,
                                       school_name=school, college_name=college,
                                       owner_admin_id=owner.id)
            self.db.add(campus_class)
            self.db.flush()
        membership = self.db.query(ClassMembership).filter(
            ClassMembership.student_id == student.id).first()
        if membership is None:
            membership = ClassMembership(class_id=campus_class.id, student_id=student.id,
                                         status="APPROVED", requested_by="ROSTER",
                                         reviewed_by=owner.id, review_note="学校名册自动归属")
            self.db.add(membership)
        else:
            membership.class_id = campus_class.id
            membership.status = "APPROVED"
            membership.requested_by = "ROSTER"
            membership.reviewed_by = owner.id
            membership.review_note = "学校名册自动归属"
            membership.updated_at = datetime.utcnow()
