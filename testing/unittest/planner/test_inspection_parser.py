from aruntime.planner.models import InspectionRequest
from aruntime.planner.parser import normalize_inspection_payload


def test_normalize_inspection_extracts_task_files():
    payload = {
        "tasks": [
            {"id": 1, "file": "app/auth.py", "description": "inspect auth"},
            {"id": 2, "file": "app/orders.py", "description": "inspect orders"},
            {"id": 3, "file": "app/auth.py", "description": "duplicate"},
        ]
    }

    inspection = InspectionRequest(**normalize_inspection_payload(payload))

    assert inspection.files == ["app/auth.py", "app/orders.py"]
    assert inspection.searches == []
