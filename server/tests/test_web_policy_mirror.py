import json
from pathlib import Path

from app.auth.policy import RULES, OwnerRule


def test_web_policy_rules_mirror_server():
    path = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "policy-rules.json"
    mirror = json.loads(path.read_text("utf-8"))
    names = {OwnerRule.NONE: "none", OwnerRule.ALWAYS: "always", OwnerRule.DEVELOPER_ONLY: "developer_only"}
    expected = {
        str(a): {"min_role": r.min_role, "local_only": r.local_only, "owner": names[r.owner]}
        for a, r in RULES.items()
    }
    assert mirror == expected
