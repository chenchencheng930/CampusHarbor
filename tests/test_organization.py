import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import hash_password
from app.models.entities import UserAccount
from app.services.organization import OrganizationService


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.school_admin = UserAccount(username="school", display_name="校级", password_hash=hash_password("password123"), public_uid="ADM-SCHOOL", admin_scope="SCHOOL", school_name="演示大学")
        self.school_admin.roles = {"ROLE_ADMIN", "ROLE_USER"}
        self.college_admin = UserAccount(username="college", display_name="院级", password_hash=hash_password("password123"), public_uid="ADM-COLLEGE", admin_scope="COLLEGE", school_name="演示大学", college_name="计算机学院")
        self.college_admin.roles = {"ROLE_ADMIN", "ROLE_USER"}
        self.student = UserAccount(username="student-x", display_name="学生", password_hash=hash_password("password123"), public_uid="STU-001", school_name="演示大学", college_name="计算机学院")
        self.student.roles = {"ROLE_USER"}
        self.db.add_all([self.school_admin, self.college_admin, self.student])
        self.db.commit()
        self.service = OrganizationService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_class_uid_application_and_privacy_safe_approval(self):
        campus_class = self.service.create_class(self.college_admin, "软件工程1班", "演示大学", "计算机学院")
        self.assertTrue(campus_class["uid"].startswith("CLS-"))
        applied = self.service.apply(self.student, campus_class["uid"])
        self.assertEqual(applied["status"], "PENDING")
        applications = self.service.applications(self.college_admin)
        self.assertEqual(applications[0]["student"]["uid"], "STU-001")
        approved = self.service.review(self.college_admin, applied["id"], "APPROVED")
        self.assertEqual(approved["status"], "APPROVED")

    def test_school_admin_can_manage_college_class_but_college_admin_is_scoped(self):
        campus_class = self.service.create_class(self.school_admin, "数学1班", "演示大学", "数学学院")
        self.assertTrue(campus_class["uid"])
        with self.assertRaises(ValueError):
            self.service.create_class(self.college_admin, "数学2班", "演示大学", "数学学院")

    def test_student_search_is_scoped(self):
        self.assertEqual(self.service.search_students(self.college_admin, "STU-001")[0]["uid"], "STU-001")
        self.assertEqual(self.service.search_students(self.college_admin, "not-found"), [])

    def test_class_search_requires_a_real_query_and_escapes_wildcards(self):
        campus_class = self.service.create_class(self.college_admin, "软件工程1班", "演示大学", "计算机学院")

        for broad_query in ("", " ", "2", "%", "_", "%_", "__"):
            with self.subTest(query=broad_query):
                self.assertEqual(self.service.search_classes(self.student, broad_query), [])

        self.assertEqual(self.service.search_classes(self.student, "软件工程")[0]["uid"], campus_class["uid"])
        self.assertEqual(self.service.search_classes(self.student, campus_class["uid"].lower())[0]["uid"], campus_class["uid"])
        self.assertEqual(self.service.search_classes(self.student, "绝对不存在的班级"), [])

    def test_student_can_leave_and_reapply_to_an_approved_class(self):
        campus_class = self.service.create_class(self.college_admin, "软件工程1班", "演示大学", "计算机学院")
        application = self.service.apply(self.student, campus_class["uid"])
        self.service.review(self.college_admin, application["id"], "APPROVED")

        self.assertEqual(self.service.mine(self.student)[0]["status"], "APPROVED")
        left = self.service.leave(self.student, campus_class["uid"])
        self.assertEqual(left["status"], "LEFT")
        self.assertEqual(self.service.mine(self.student), [])

        reapplied = self.service.apply(self.student, campus_class["uid"])
        self.assertEqual(reapplied["status"], "PENDING")
        self.assertEqual(self.service.mine(self.student)[0]["status"], "PENDING")

    def test_student_cannot_have_two_approved_classes(self):
        first_class = self.service.create_class(self.college_admin, "软件工程1班", "演示大学", "计算机学院")
        second_class = self.service.create_class(self.college_admin, "软件工程2班", "演示大学", "计算机学院")
        first_application = self.service.apply(self.student, first_class["uid"])
        second_application = self.service.apply(self.student, second_class["uid"])

        self.service.review(self.college_admin, first_application["id"], "APPROVED")
        with self.assertRaisesRegex(ValueError, "已加入其他班级"):
            self.service.review(self.college_admin, second_application["id"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
