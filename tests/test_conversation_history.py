import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import ChatMessage, ChatSession, UserAccount
from app.services.report import ReportService


class ConversationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.student = UserAccount(
            username="student-a",
            display_name="学生 A",
            password_hash="hash",
            public_uid="STU-A",
        )
        self.other = UserAccount(
            username="student-b",
            display_name="学生 B",
            password_hash="hash",
            public_uid="STU-B",
        )
        self.db.add_all([self.student, self.other])
        self.db.commit()
        self.session = ChatSession(public_id="session-a", title="最近有点累", user_id=self.student.id)
        self.foreign_session = ChatSession(public_id="session-b", title="其他人的对话", user_id=self.other.id)
        self.db.add_all([self.session, self.foreign_session])
        self.db.commit()
        self.db.add_all([
            ChatMessage(user_id=self.student.id, session_id=self.session.id, role="user", content="最近有点累"),
            ChatMessage(user_id=self.student.id, session_id=self.session.id, role="assistant", content="这种感觉持续多久了？"),
            ChatMessage(user_id=self.other.id, session_id=self.foreign_session.id, role="user", content="私密内容"),
        ])
        self.db.commit()
        self.service = ReportService(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_student_list_only_contains_own_sessions(self):
        rows = self.service.conversations(self.student.id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].sessionId, "session-a")
        self.assertEqual(rows[0].messageCount, 2)

    def test_student_can_restore_own_conversation(self):
        conversation = self.service.conversation("session-a", redact_sensitive=False, user_id=self.student.id)

        self.assertEqual([message.role for message in conversation.messages], ["user", "assistant"])
        self.assertEqual(conversation.messages[1].content, "这种感觉持续多久了？")

    def test_student_cannot_read_another_students_conversation(self):
        with self.assertRaisesRegex(ValueError, "Session not found"):
            self.service.conversation("session-b", redact_sensitive=False, user_id=self.student.id)


if __name__ == "__main__":
    unittest.main()
