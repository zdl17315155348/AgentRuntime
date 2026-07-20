from __future__ import annotations

import json


def build_inspection_prompt(user_goal: str, repo_tree: list[str], readme_summary: str, roles: list[str], limits: dict) -> str:
    return json.dumps(
        {
            "goal": user_goal,
            "repo_tree": repo_tree,
            "readme_summary": readme_summary,
            "roles": roles,
            "limits": limits,
            "output": "InspectionRequest JSON only",
        },
        ensure_ascii=False,
    )


def build_plan_prompt(user_goal: str, inspection_context: dict, roles: list[str]) -> str:
    return json.dumps(
        {
            "goal": user_goal,
            "inspection_context": inspection_context,
            "roles": roles,
            "output": {
                "instruction": "Return PlanSpec JSON only. Do not wrap it in another object.",
                "required_shape": {
                    "version": "1.0",
                    "summary": "short workflow summary",
                    "tasks": [
                        {
                            "local_id": "fix_auth",
                            "role": "coder",
                            "goal": "specific code change goal",
                            "dependencies": [],
                            "required_capability": {"can_code": True, "language": "python"},
                        },
                        {
                            "local_id": "regression",
                            "role": "tester",
                            "goal": "run pytest",
                            "dependencies": ["fix_auth"],
                            "required_capability": {"can_test": True, "tool": "run_pytest"},
                        },
                        {
                            "local_id": "review",
                            "role": "reviewer",
                            "goal": "review patch and test evidence",
                            "dependencies": ["regression"],
                            "required_capability": {"can_review": True},
                        },
                    ],
                },
            },
        },
        ensure_ascii=False,
    )
