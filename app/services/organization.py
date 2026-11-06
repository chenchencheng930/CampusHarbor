from __future__ import annotations

import secrets
import string
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.entities import CampusClass, ClassMembership, UserAccount


class OrganizationError(ValueError):
    pass


def new_uid(prefix: str) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(12))


class OrganizationService:
    def __init__(self, db: Session):
        self.db = db

    def create_class(self, admin: UserAccount, name: str, school_name: str, college_name: str) -> dict:
        self.require_scope(admin, "COLLEGE")
        school_name = (school_name or admin.school_name).strip()
        college_name = (college_name or admin.college_name).strip()
        if admin.admin_scope == "COLLEGE" and college_name != admin.college_name:
            raise OrganizationError("院级管理员只能管理所属学院")
        if admin.admin_scope == "COLLEGE" and school_name != admin.school_name:
            raise OrganizationError("院级管理员只能管理所属学校")
        if not name.strip() or not school_name or not college_name:
            raise OrganizationError("班级名称、学校和学院不能为空")
        campus_class = CampusClass(
            public_uid=self._unique_uid("CLS"),
            name=name.strip(),
            school_name=school_name,
            college_name=college_name,
            owner_admin_id=admin.id,
        )
        self.db.add(campus_class)
        self.db.commit()
        self.db.refresh(campus_class)
        return self.class_view(campus_class)

    def search_classes(self, student: UserAccount, query: str) -> list[dict]:
        query = (query or "").strip()
        # Never expose the entire class directory through an empty/broad query.
        # One-character searches are too noisy (e.g. "2" matches every cohort),
        # and SQL LIKE metacharacters must be treated as literal input.
        if len(query) < 2:
            return []
        statement = self.db.query(CampusClass).filter(CampusClass.status == "ACTIVE")
        if student.school_name:
            statement = statement.filter(CampusClass.school_name == student.school_name)
        statement = statement.filter(or_(
            CampusClass.public_uid == query.upper(),
            CampusClass.name.contains(query, autoescape=True),
            CampusClass.college_name.contains(query, autoescape=True),
        ))
        return [self.class_view(item) for item in statement.order_by(CampusClass.created_at.desc()).limit(50).all()]

    def apply(self, student: UserAccount, class_uid: str) -> dict:
        self.require_student(student)
        campus_class = self._class(class_uid)
        if campus_class.school_name != student.school_name:
            raise OrganizationError("只能申请加入本校班级")
        joined = self.db.query(ClassMembership).filter(
            ClassMembership.student_id == student.id,
            ClassMembership.status == "APPROVED",
        ).first()
        if joined is not None:
            raise OrganizationError("你已经加入班级，请先退出当前班级")
        existing = self.db.query(ClassMembership).filter(
            ClassMembership.class_id == campus_class.id,
            ClassMembership.student_id == student.id,
        ).first()
        if existing:
            if existing.status == "LEFT":
                existing.status = "PENDING"
                existing.requested_by = "STUDENT"
                existing.reviewed_by = None
                existing.review_note = ""
                existing.updated_at = datetime.utcnow()
                self.db.add(existing)
                self.db.commit()
            return self.membership_view(existing)
        membership = ClassMembership(class_id=campus_class.id, student_id=student.id, status="PENDING", requested_by="STUDENT")
        self.db.add(membership)
        self.db.commit()
        self.db.refresh(membership)
        return self.membership_view(membership)

    def mine(self, student: UserAccount) -> list[dict]:
        rows = self.db.query(ClassMembership).filter(
            ClassMembership.student_id == student.id,
            ClassMembership.status.in_(["PENDING", "INVITED", "APPROVED"]),
        ).order_by(ClassMembership.updated_at.desc()).all()
        return [self.membership_view(row) for row in rows]

    def leave(self, student: UserAccount, class_uid: str) -> dict:
        self.require_student(student)
        campus_class = self._class(class_uid)
        membership = self.db.query(ClassMembership).filter(
            ClassMembership.class_id == campus_class.id,
            ClassMembership.student_id == student.id,
            ClassMembership.status == "APPROVED",
        ).first()
        if membership is None:
            raise OrganizationError("你当前不属于该班级")
        membership.status = "LEFT"
        membership.reviewed_by = None
        membership.review_note = "学生主动退出班级"
        membership.updated_at = datetime.utcnow()
        self.db.add(membership)
        self.db.commit()
        return self.membership_view(membership)

    def applications(self, admin: UserAccount, status: str = "PENDING") -> list[dict]:
        self.require_scope(admin, "COLLEGE")
        query = self.db.query(ClassMembership, CampusClass, UserAccount).join(
            CampusClass, ClassMembership.class_id == CampusClass.id
        ).join(UserAccount, ClassMembership.student_id == UserAccount.id)
        query = query.filter(ClassMembership.status == status)
        if admin.admin_scope == "COLLEGE":
            query = query.filter(CampusClass.school_name == admin.school_name, CampusClass.college_name == admin.college_name)
        elif admin.admin_scope == "SCHOOL":
            query = query.filter(CampusClass.school_name == admin.school_name)
        return [self.application_view(membership, campus_class, student) for membership, campus_class, student in query.order_by(ClassMembership.created_at.asc()).limit(200).all()]

    def review(self, admin: UserAccount, membership_id: int, decision: str, note: str = "") -> dict:
        self.require_scope(admin, "COLLEGE")
        row = self.db.query(ClassMembership, CampusClass).join(CampusClass, ClassMembership.class_id == CampusClass.id).filter(ClassMembership.id == membership_id).first()
        if row is None:
            raise OrganizationError("申请不存在")
        membership, campus_class = row
        self._assert_can_manage_class(admin, campus_class)
        if membership.status not in {"PENDING", "INVITED"}:
            raise OrganizationError("该申请已处理")
        if decision not in {"APPROVED", "REJECTED"}:
            raise OrganizationError("无效审批动作")
        if decision == "APPROVED":
            joined = self.db.query(ClassMembership).filter(
                ClassMembership.student_id == membership.student_id,
                ClassMembership.status == "APPROVED",
                ClassMembership.id != membership.id,
            ).first()
            if joined is not None:
                raise OrganizationError("该学生已加入其他班级")
        membership.status = decision
        membership.reviewed_by = admin.id
        membership.review_note = note.strip()[:512]
        membership.updated_at = datetime.utcnow()
        self.db.add(membership)
        self.db.commit()
        return self.membership_view(membership)

    def search_students(self, admin: UserAccount, query: str) -> list[dict]:
        self.require_scope(admin, "COLLEGE")
        query = (query or "").strip()
        statement = self.db.query(UserAccount).filter(UserAccount.account_status == "ACTIVE", UserAccount.roles_csv.notlike("%ROLE_ADMIN%"))
        if admin.admin_scope == "COLLEGE":
            statement = statement.filter(UserAccount.school_name == admin.school_name, UserAccount.college_name == admin.college_name)
        else:
            statement = statement.filter(UserAccount.school_name == admin.school_name)
        if query:
            statement = statement.filter(or_(UserAccount.public_uid == query, UserAccount.username.contains(query), UserAccount.display_name.contains(query)))
        return [self.student_view(item) for item in statement.limit(50).all()]

    def invite(self, admin: UserAccount, class_uid: str, student_uids: list[str]) -> list[dict]:
        self.require_scope(admin, "COLLEGE")
        campus_class = self._class(class_uid)
        self._assert_can_manage_class(admin, campus_class)
        results = []
        for uid in dict.fromkeys(item.strip() for item in student_uids if item.strip()):
            student = self.db.query(UserAccount).filter(UserAccount.public_uid == uid).first()
            if student is None or "ROLE_ADMIN" in student.roles:
                continue
            if student.school_name != campus_class.school_name or student.college_name != campus_class.college_name:
                continue
            membership = self.db.query(ClassMembership).filter(ClassMembership.class_id == campus_class.id, ClassMembership.student_id == student.id).first()
            if membership is None:
                membership = ClassMembership(class_id=campus_class.id, student_id=student.id, status="INVITED", requested_by="ADMIN")
                self.db.add(membership)
            elif membership.status in {"REJECTED", "PENDING"}:
                membership.status = "INVITED"
                membership.requested_by = "ADMIN"
            results.append(self.membership_view(membership))
        self.db.commit()
        return results

    def classes_for_admin(self, admin: UserAccount) -> list[dict]:
        self.require_scope(admin, "COLLEGE")
        query = self.db.query(CampusClass).filter(CampusClass.status == "ACTIVE")
        if admin.admin_scope == "COLLEGE":
            query = query.filter(CampusClass.school_name == admin.school_name, CampusClass.college_name == admin.college_name)
        else:
            query = query.filter(CampusClass.school_name == admin.school_name)
        return [self.class_view(item) for item in query.order_by(CampusClass.created_at.desc()).all()]

    @staticmethod
    def require_student(user: UserAccount) -> None:
        if "ROLE_ADMIN" in user.roles:
            raise OrganizationError("管理员账号不能执行学生申请操作")

    @staticmethod
    def require_scope(user: UserAccount, minimum: str) -> None:
        order = {"NONE": 0, "COLLEGE": 1, "SCHOOL": 2}
        if "ROLE_ADMIN" not in user.roles or order.get(user.admin_scope, 0) < order[minimum]:
            raise OrganizationError("没有足够的管理员权限")

    def _assert_can_manage_class(self, admin: UserAccount, campus_class: CampusClass) -> None:
        self.require_scope(admin, "COLLEGE")
        if campus_class.school_name != admin.school_name or (admin.admin_scope == "COLLEGE" and campus_class.college_name != admin.college_name):
            raise OrganizationError("无权管理该班级")

    def _class(self, uid: str) -> CampusClass:
        campus_class = self.db.query(CampusClass).filter(CampusClass.public_uid == uid, CampusClass.status == "ACTIVE").first()
        if campus_class is None:
            raise OrganizationError("班级不存在")
        return campus_class

    def _unique_uid(self, prefix: str) -> str:
        for _ in range(10):
            uid = new_uid(prefix)
            exists = self.db.query(CampusClass if prefix == "CLS" else UserAccount).filter_by(public_uid=uid).first()
            if exists is None:
                return uid
        raise OrganizationError("无法生成唯一 UID，请稍后重试")

    @staticmethod
    def class_view(item: CampusClass) -> dict:
        return {"uid": item.public_uid, "name": item.name, "schoolName": item.school_name, "collegeName": item.college_name, "status": item.status, "createdAt": item.created_at}

    def membership_view(self, item: ClassMembership) -> dict:
        campus_class = self.db.get(CampusClass, item.class_id)
        student = self.db.get(UserAccount, item.student_id)
        return {"id": item.id, "status": item.status, "requestedBy": item.requested_by, "reviewNote": item.review_note, "class": self.class_view(campus_class) if campus_class else None, "student": self.student_view(student) if student else None, "updatedAt": item.updated_at}

    @staticmethod
    def student_view(student: UserAccount) -> dict:
        return {"uid": student.public_uid, "displayName": student.display_name, "username": student.username, "schoolName": student.school_name, "collegeName": student.college_name}

    def application_view(self, membership: ClassMembership, campus_class: CampusClass, student: UserAccount) -> dict:
        return {"id": membership.id, "status": membership.status, "requestedBy": membership.requested_by, "class": self.class_view(campus_class), "student": self.student_view(student), "createdAt": membership.created_at, "updatedAt": membership.updated_at}
