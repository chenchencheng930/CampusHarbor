import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import hash_password
from app.models.entities import ClassMembership, StudentRoster, UserAccount
from app.services.roster import RosterImportError, RosterService


class RosterWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.system = self.admin("system", "校级管理员", "SYSTEM_ADMIN", "SCHOOL", "")
        self.advisor = self.admin("advisor", "计院辅导员", "ADVISOR", "COLLEGE", "计算机学院")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def admin(self, username, name, role, scope, college, verified="VERIFIED"):
        user = UserAccount(username=username, display_name=name,
            password_hash=hash_password("password123"), public_uid=f"ADM-{username}",
            roles_csv="ROLE_ADMIN,ROLE_USER", admin_scope=scope, admin_role=role,
            admin_verification_status=verified, school_name="演示大学", college_name=college,
            admin_employee_number=f"EMP-{username}")
        self.db.add(user); self.db.flush(); return user

    def student(self, number="20260001", name="张同学"):
        user = UserAccount(username=f"s-{number}", display_name=name,
            password_hash=hash_password("password123"), public_uid=f"STU-{number}",
            student_number=number, roles_csv="ROLE_USER")
        self.db.add(user); self.db.flush(); return user

    def test_system_import_assigns_existing_student_and_class(self):
        student = self.student()
        result = RosterService(self.db).import_csv(self.system,
            "学号,姓名,学校,学院,班级\n20260001,张同学,演示大学,计算机学院,软件工程1班\n".encode())
        self.assertEqual(result["assigned"], 1)
        self.db.refresh(student)
        self.assertTrue(student.identity_verified)
        self.assertEqual(student.advisor_admin_id, self.advisor.id)
        self.assertEqual(self.db.query(ClassMembership).one().status, "APPROVED")

    def test_roster_before_registration_activates_later(self):
        service = RosterService(self.db)
        service.import_csv(self.advisor,
            "学号,姓名,学院\n20260002,李同学,计算机学院\n".encode())
        student = self.student("20260002", "李同学")
        self.assertTrue(service.activate_registration(student))
        self.db.commit(); self.db.refresh(student)
        self.assertEqual(student.advisor_admin_id, self.advisor.id)
        self.assertTrue(student.identity_verified)
        self.assertEqual(self.db.query(StudentRoster).filter_by(student_number="20260002").one().user_id, student.id)

    def test_advisor_cannot_import_another_college(self):
        result = RosterService(self.db).import_csv(self.advisor,
            "学号,姓名,学院\n20260003,王同学,外国语学院\n".encode())
        self.assertIn("本人负责学院", result["errors"][0]["message"])

    def test_new_roster_advisor_replaces_old_college_advisor(self):
        pending = self.admin("advisor2", "另一辅导员", "ADVISOR", "COLLEGE", "计算机学院", "PENDING")
        self.db.commit()
        result = RosterService(self.db).import_csv(self.system,
            "工号,姓名,账号,学校,学院,身份\nEMP-advisor2,另一辅导员,advisor2,演示大学,计算机学院,ADVISOR\n".encode())
        self.db.refresh(self.advisor); self.db.refresh(pending)
        self.assertEqual(result["staffActivated"], 1)
        self.assertEqual(self.advisor.admin_verification_status, "REJECTED")
        self.assertEqual(pending.admin_verification_status, "VERIFIED")

    def test_imported_advisor_bulk_assigns_existing_college_students(self):
        self.advisor.admin_verification_status = "REJECTED"
        pending = self.admin("advisor-new", "新辅导员", "ADVISOR", "COLLEGE", "计算机学院", "PENDING")
        student = self.student("20260004", "赵同学")
        student.school_name = "演示大学"; student.college_name = "计算机学院"
        self.db.commit()
        result = RosterService(self.db).import_csv(self.system,
            "工号,姓名,账号,学校,学院,身份\nEMP-advisor-new,新辅导员,advisor-new,演示大学,计算机学院,ADVISOR\n".encode())
        self.assertEqual(result["assigned"], 1)
        self.db.refresh(student)
        self.assertEqual(student.advisor_admin_id, pending.id)


if __name__ == "__main__":
    unittest.main()
