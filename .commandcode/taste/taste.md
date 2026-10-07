# ollama
- Use Ollama (not Anthropic) as the AI provider for all backend inference. Confidence: 0.70
- Use SSE streaming endpoints for variable identification to avoid long wait times. Confidence: 0.65

# testing
- Use Vitest as the testing framework. Confidence: 0.70

# variables
- Deduplicate variables strictly in both FE and BE — no duplicate variable names allowed. Confidence: 0.75
- Strip curly braces from identified variables before applying them in the document. Confidence: 0.75

# frontend
- Use longest-wins cascade for content control wrapping — overlapping content controls resolve by keeping the longest match. Confidence: 0.70

# skills
- Store project AI prompt skills in the `.claude/skills/` directory as markdown files. Confidence: 0.65

# style
- Convert Python code examples to JavaScript/TypeScript when creating skills for this project. Confidence: 0.65
