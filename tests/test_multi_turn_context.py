import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.autonomous import ContextAgent, ResponseAgent, UnderstandingAgent
from app.agents.event_driven_runtime import EventDrivenAgentRuntimeService
from app.agents.events import AgentArtifact, AgentTask, CollaborationBlackboard
from app.core.config import Settings
from app.core.database import Base
from app.core.enums import IntentType, RiskLevel
from app.models.entities import ChatMessage, ChatSession, UserAccount
from app.schemas.dtos import AiMessage
from app.services.skills import MindBridgeSkillLibrary


class MultiTurnContextTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.settings = Settings(
            _env_file=None,
            ai_provider="mock",
            redis_memory_enabled=False,
            knowledge_vector_enabled=False,
        )
        self.user = UserAccount(username="context-test", display_name="测试学生", password_hash="hash", public_uid="STU-CTX")
        self.other = UserAccount(username="other-test", display_name="其他学生", password_hash="hash", public_uid="STU-OTHER")
        self.db.add_all([self.user, self.other])
        self.db.flush()
        self.session = ChatSession(public_id="context-session", user_id=self.user.id, title="上下文回归")
        self.other_session = ChatSession(public_id="other-session", user_id=self.other.id, title="隔离会话")
        self.db.add_all([self.session, self.other_session])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def save_history(self, messages):
        for role, content in messages:
            self.db.add(ChatMessage(user_id=self.user.id, session_id=self.session.id, role=role, content=content))
        self.db.commit()

    def run_turn(self, text):
        return EventDrivenAgentRuntimeService(self.db, self.settings).run(self.user, self.session, text, text)

    def board(self, text, history=()):
        return CollaborationBlackboard(turn_id="test-turn", user_input=text, model_input=text).add_artifact(
            AgentArtifact(id="history", owner="Harness", kind="conversation_history", payload={"messages": list(history)})
        )

    def test_ordinary_chat_retains_previous_messages_without_rag(self):
        self.save_history([
            ("user", "解释 Python 列表推导式"),
            ("assistant", "可以写成 [x * 2 for x in numbers]。"),
        ])
        with patch("app.services.knowledge.KnowledgeService.retrieve") as retrieve:
            result = self.run_turn("给我一个加上条件判断的例子")

        self.assertEqual(result.intent, IntentType.CHAT)
        history = [(m.role, m.content) for m in result.response_messages if m.role != "system"]
        self.assertEqual(history, [
            ("user", "解释 Python 列表推导式"),
            ("assistant", "可以写成 [x * 2 for x in numbers]。"),
            ("user", "给我一个加上条件判断的例子"),
        ])
        retrieve.assert_not_called()
        kinds = [artifact.kind for artifact in result.collaboration_artifacts]
        self.assertLess(kinds.index("context"), kinds.index("response_proposal"))
        self.assertIn("safety_review", kinds)

    def test_brief_followup_keeps_body_details_and_is_not_a_first_consult(self):
        self.save_history([
            ("user", "最近有点累"),
            ("assistant", "最近发生了什么，让你觉得这么累？"),
            ("user", "身体，最近肩颈痛"),
            ("assistant", "肩颈痛是在什么情况下更明显？"),
        ])
        result = self.run_turn("可是我心情不好")

        self.assertEqual(result.intent, IntentType.CONSULT)
        content = "\n".join(m.content for m in result.response_messages)
        self.assertIn("身体，最近肩颈痛", content)
        self.assertIn("历史中相关的信息和最新补充", content)
        self.assertIn("不重复历史里已经问过或回答过的问题", content)
        self.assertNotIn("这是一个信息很少的首次情绪表达", content)
        self.assertIn("已连续两轮追问", content)
        self.assertIn("已经问过，不要再问相同或换措辞的同一问题", content)
        self.assertIn("学生正在把重点转向情绪", content)

    def test_answered_duration_is_available_to_response_agent(self):
        self.save_history([
            ("user", "要考试了很焦虑"),
            ("assistant", "这种焦虑持续多久了？"),
        ])
        result = self.run_turn("两周多吧，平时总是胡思乱想")

        self.assertEqual(result.intent, IntentType.CONSULT)
        history = [m.content for m in result.response_messages if m.role != "system"]
        self.assertEqual(history, ["要考试了很焦虑", "这种焦虑持续多久了？", "两周多吧，平时总是胡思乱想"])
        self.assertIn("不要重复询问已回答的持续时间", result.response_messages[0].content)
        self.assertIn("当前补充包含持续时间", result.response_messages[0].content)

    def test_first_brief_checkin_asks_for_a_concrete_event(self):
        result = self.run_turn("最近有点累")

        content = "\n".join(m.content for m in result.response_messages if m.role == "system")
        self.assertIn("这是一个信息很少的首次情绪表达", content)
        self.assertIn("只追问一个与具体经历有关的问题", content)
        self.assertEqual(sum(m.role == "user" for m in result.response_messages), 1)

    def test_concrete_event_is_reflected_instead_of_restarting_intake(self):
        result = self.run_turn("昨天室友当着同学的面嘲笑我成绩差，我很难过")

        self.assertIn("学生已经提供具体事件", result.response_messages[0].content)
        self.assertIn("不再泛问发生了什么", result.response_messages[0].content)
        self.assertEqual(result.response_messages[-1].content, "昨天室友当着同学的面嘲笑我成绩差，我很难过")

    def test_short_body_followup_inherits_recent_consult_without_intent_llm(self):
        history = [AiMessage(role="user", content="最近有点累"), AiMessage(role="assistant", content="具体哪里不舒服？")]
        agent = UnderstandingAgent(Mock())
        with patch.object(agent, "client") as client:
            intent = agent._classify("身体，最近肩颈痛", self.board("身体，最近肩颈痛", history))

        self.assertEqual(intent, IntentType.CONSULT)
        client.assert_not_called()

    def test_explicit_general_task_switches_out_of_consult(self):
        self.save_history([("user", "最近有点累"), ("assistant", "最近发生了什么？")])
        result = self.run_turn("解释 Python 的字典怎么使用")

        self.assertEqual(result.intent, IntentType.CHAT)
        proposal = next(a for a in result.collaboration_artifacts if a.kind == "response_proposal")
        self.assertEqual(proposal.payload["mode"], "normal_chat")

    def test_emotional_carryover_stops_after_a_general_topic_switch(self):
        history = [
            AiMessage(role="user", content="最近有点累"),
            AiMessage(role="assistant", content="具体发生了什么？"),
            AiMessage(role="user", content="解释 Python 的字典"),
            AiMessage(role="assistant", content="字典由键值对构成。"),
        ]
        agent = UnderstandingAgent(Mock())
        with patch.object(agent, "private_memory", return_value=[]), patch.object(agent, "client") as client:
            client.return_value.complete.return_value = "CHAT"
            intent = agent._classify("再举个例子", self.board("再举个例子", history))

        self.assertEqual(intent, IntentType.CHAT)
        prompt = client.return_value.complete.call_args.args[0]
        self.assertIn("字典由键值对构成", prompt[1].content)

    def test_hard_high_risk_still_overrides_with_conversation_history(self):
        self.save_history([("user", "你好"), ("assistant", "你好，想聊些什么？")])
        result = self.run_turn("我想伤害自己")

        self.assertEqual(result.intent, IntentType.RISK)
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertIn("高风险处理规则", result.response_messages[0].content)
        self.assertTrue(any(a.kind == "safety_review" and a.payload["approved"] for a in result.collaboration_artifacts))

    def test_response_agent_waits_for_context_even_in_normal_chat(self):
        board = self.board("解释 Python")
        board = board.add_artifact(AgentArtifact(id="intent", owner="UnderstandingAgent", kind="intent", payload={"intent": "CHAT"}))
        board = board.add_artifact(AgentArtifact(id="risk", owner="SafetyAgent", kind="risk", payload={"risk": "LOW"}))
        decision = ResponseAgent(Mock()).decide(AgentTask(id="response", title="回复"), board)

        self.assertFalse(decision.claim)
        self.assertIn("history", decision.reason)

    def test_context_query_uses_user_facts_not_previous_generic_advice(self):
        agent = ContextAgent(Mock())
        history = [
            AiMessage(role="user", content="要考试了很焦虑"),
            AiMessage(role="assistant", content="早点睡，多运动。"),
        ]
        with patch.object(agent, "client") as client:
            query = agent._rewrite_query(history, "担心复习来不及")

        self.assertIn("考试", query)
        self.assertIn("复习来不及", query)
        self.assertNotIn("多运动", query)
        client.assert_not_called()

    def test_short_body_followup_does_not_trigger_irrelevant_rag(self):
        self.save_history([("user", "最近有点累"), ("assistant", "具体哪里不舒服？")])
        with patch("app.services.knowledge.KnowledgeService.retrieve") as retrieve:
            result = self.run_turn("身体，最近肩颈痛")

        self.assertEqual(result.intent, IntentType.CONSULT)
        retrieve.assert_not_called()

    def test_short_resource_request_still_retrieves_knowledge(self):
        with patch("app.services.knowledge.KnowledgeService.retrieve", return_value=[]) as retrieve:
            result = self.run_turn("心理中心怎么预约")

        self.assertEqual(result.intent, IntentType.CONSULT)
        retrieve.assert_called_once()

    def test_concrete_emotional_disclosure_does_not_trigger_rag(self):
        with patch("app.services.knowledge.KnowledgeService.retrieve") as retrieve:
            result = self.run_turn("昨天室友当着同学的面嘲笑我成绩差，我很难过")

        self.assertEqual(result.intent, IntentType.CONSULT)
        retrieve.assert_not_called()

    def test_referral_skill_is_conditional_not_a_low_risk_reply_template(self):
        brief = MindBridgeSkillLibrary.response_skill_names(IntentType.CONSULT, RiskLevel.LOW, "最近有点累")
        resource = MindBridgeSkillLibrary.response_skill_names(IntentType.CONSULT, RiskLevel.LOW, "心理中心怎么预约")
        medium = MindBridgeSkillLibrary.response_skill_names(IntentType.CONSULT, RiskLevel.MEDIUM, "难过")
        high = MindBridgeSkillLibrary.response_skill_names(IntentType.RISK, RiskLevel.HIGH, "我想伤害自己")

        self.assertEqual(brief, ["supportive_response_baseline"])
        self.assertIn("referral_resource_guidance", resource)
        self.assertIn("referral_resource_guidance", medium)
        self.assertIn("high_risk_safety_plan", high)

    def test_history_loaded_once_and_other_sessions_excluded(self):
        self.save_history([("user", "解释 Python 列表"), ("assistant", "可以使用方括号。")])
        self.db.add(ChatMessage(user_id=self.other.id, session_id=self.other_session.id, role="user", content="其他学生的私密消息"))
        self.db.commit()
        original_load = ContextAgent._load_history
        with patch.object(ContextAgent, "_load_history", autospec=True, side_effect=original_load) as load:
            result = self.run_turn("给我一个例子")

        self.assertEqual(load.call_count, 1)
        self.assertNotIn("其他学生的私密消息", "\n".join(m.content for m in result.response_messages))


if __name__ == "__main__":
    unittest.main()
