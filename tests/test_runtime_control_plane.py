import unittest
import hashlib

from app.core.security import hash_password, verify_password
from app.services.agent_policy import AgentPolicyViolation, AgentRunBudget, AgentRunPolicy


class RuntimeControlPlaneTests(unittest.TestCase):
    def test_password_hash_is_salted_and_legacy_hash_remains_readable(self):
        hashed = hash_password("correct horse battery staple")
        self.assertTrue(hashed.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("correct horse battery staple", hashed))
        self.assertFalse(verify_password("wrong", hashed))
        self.assertTrue(verify_password("student123", hashlib.sha256(b"student123").hexdigest()))

    def test_agent_budget_enforces_steps_and_tool_permissions(self):
        budget = AgentRunBudget(AgentRunPolicy(max_steps=1, allowed_tools=frozenset({"llm.intent"})))
        budget.authorize_tool("UnderstandingAgent", "llm.intent")
        with self.assertRaises(AgentPolicyViolation):
            budget.authorize_tool("UnderstandingAgent", "dangerous.delete")

    def test_output_is_bounded_without_exposing_secrets(self):
        budget = AgentRunBudget(AgentRunPolicy(max_output_chars=10))
        value = budget.validate_output("0123456789abcdef")
        self.assertLessEqual(len(value), 40)
        self.assertTrue(budget.events)


if __name__ == "__main__":
    unittest.main()
