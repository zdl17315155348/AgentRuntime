Repair the current integration failure using the test summary and existing patch references.
Return only one JSON object, with no Markdown, prose, code fences, or extra text.

Required JSON fields:
- completed: boolean
- summary: string
- tests_run: array of strings
- remaining_issues: array of strings

Use completed=true only when the integration failure is repaired.
Use remaining_issues=[] when there are no known remaining issues.
