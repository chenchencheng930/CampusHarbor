import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.core.enums import RiskCaseStatus
from app.models.entities import RiskCase
from app.services.tools import ToolOrchestrationService


class RiskCaseFollowUpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "case.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.service = ToolOrchestrationService(self.db, Settings())
        self.case = RiskCase(
            report_id=1001,
            risk_level="HIGH",
            status=RiskCaseStatus.OPEN.value,
            owner="unassigned",
            summary="test",
        )
        self.db.add(self.case)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_acknowledge_assigns_owner_and_writes_note(self):
        case = self.service.acknowledge_case(self.case.id, "张老师", "电话联系")

        self.assertEqual(case.status, RiskCaseStatus.ACKNOWLEDGED.value)
        self.assertEqual(case.owner, "张老师")
        notes = self.service.db.execute(
            __import__("sqlalchemy").text("select actor, note from case_notes where case_id=:id"),
            {"id": case.id},
        ).all()
        self.assertEqual(notes, [("张老师", "电话联系")])

    def test_case_must_be_acknowledged_before_close(self):
        with self.assertRaisesRegex(RuntimeError, "请先接手"):
            self.service.update_case_status(self.case.id, "张老师", "CLOSED", "情况稳定")

    def test_acknowledged_case_can_be_referred_then_closed(self):
        self.service.acknowledge_case(self.case.id, "张老师")
        referred = self.service.update_case_status(self.case.id, "张老师", "REFERRED", "转心理中心")
        self.assertEqual(referred.status, RiskCaseStatus.REFERRED.value)
        closed = self.service.update_case_status(self.case.id, "李老师", "CLOSED", "已完成交接")
        self.assertEqual(closed.status, RiskCaseStatus.CLOSED.value)


if __name__ == "__main__":
    unittest.main()
