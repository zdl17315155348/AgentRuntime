Modify the repository to satisfy the assigned repair goal. Keep changes minimal and focused.
Return only one JSON object, with no Markdown, prose, code fences, or extra text.

Required JSON fields:
- completed: boolean
- summary: string
- tests_run: array of strings
- remaining_issues: array of strings

Use completed=true only when the assigned repair goal is implemented.
Use remaining_issues=[] when there are no known remaining issues.
