Review the final diff and test result in read-only mode.
Do not modify files.
Return only one JSON object, with no Markdown, prose, code fences, or extra text.

Required JSON fields:
- approved: boolean
- requirements_covered: array of strings
- issues: array of strings
- summary: string
- artifact_id: string or null

Use issues=[] when there are no blocking issues.
