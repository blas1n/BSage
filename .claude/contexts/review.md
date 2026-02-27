---
context: review
description: Code review mode - verifying quality and compliance for BSage
---

# Review Context

You are reviewing code for BSage. Ensure adherence to standards and architecture.

## Review Checklist

### 1. Architecture Compliance

Verify against `.claude/rules/architecture.md`:

- [ ] Python 3.11+ with type hints on all public functions
- [ ] pyproject.toml + uv (no requirements.txt)
- [ ] pydantic-settings for config (no raw `os.getenv`)
- [ ] structlog for logging (not `print` or `logging.info`)
- [ ] All I/O operations are async
- [ ] Skill definitions in skill.yaml (not hardcoded)
- [ ] Dataclasses for structured data

**Check:**
```bash
# Verify no raw os.getenv
grep -r "os\.getenv\|os\.environ" bsage/ | grep -v test

# Verify no logging.info
grep -r "logging\.info\|logging\.error\|print(" bsage/ | grep -v test

# Verify type hints on function signatures
grep -r "^async def\|^def" bsage/ | grep -v "->"
```

### 2. Skill System Rules

Verify `.claude/rules/skill-system.md`:

- [ ] skill.yaml has all required fields (name, version, category, is_dangerous, description)
- [ ] skill.py uses `execute(context)` entry point
- [ ] No `bsage` import in skill.py
- [ ] Connector access via `context.connector()` only
- [ ] is_dangerous correctly set (external side effects = true)
- [ ] GardenWriter writes to correct directory (seeds/garden/actions)

**Check:**
```bash
# Check for bsage imports in skills
grep -r "from bsage\|import bsage" skills/

# Verify is_dangerous on process skills
grep -r "is_dangerous" skills/*/skill.yaml
```

### 3. Testing

Verify `.claude/rules/testing.md`:

- [ ] Unit tests present
- [ ] Coverage >= 80%
- [ ] External APIs mocked (Claude, Connectors, APScheduler)
- [ ] Error cases tested (missing skill.yaml, connector not found, etc.)

**Run:**
```bash
pytest bsage/tests/ --cov=bsage --cov-fail-under=80 --cov-report=term-missing
```

### 4. Security

Check `.claude/rules/security.md`:

- [ ] No hardcoded credentials (API keys, tokens)
- [ ] .env.example provided for new env vars
- [ ] No credentials in logs
- [ ] SafeModeGuard not bypassed
- [ ] Vault path traversal prevented
- [ ] Connector credentials in .credentials/ (gitignored)

**Check:**
```bash
# Search for hardcoded secrets
grep -r "sk-ant-\|password\s*=\s*\"" bsage/ | grep -v ".env\|test"

# Verify SafeModeGuard integration
grep -r "is_dangerous" bsage/core/
```

### 5. Code Quality

- [ ] `ruff check` passes (no lint errors)
- [ ] Async/await consistent throughout
- [ ] Error handling for I/O operations
- [ ] Meaningful log messages with context
- [ ] No unnecessary complexity

**Check:**
```bash
ruff check bsage/
ruff format --check bsage/
```

### 6. Skill / Core Integration

- [ ] Module returns correct dataclass type
- [ ] Exceptions use domain exception classes from `core/exceptions.py`
- [ ] SkillContext interface properly exposes only allowed methods
- [ ] Vault data never leaves Vault boundary (except via OutputSkill)

## Review Response Format

### Approve

```
APPROVED

All checks passed:
- Architecture compliance (type hints, pydantic-settings, structlog)
- Skill system rules followed
- Test coverage (85%)
- Security requirements
- ruff check passing

No issues found.
```

### Request Changes

```
CHANGES REQUESTED

Issues found:

1. Skill system violation (HIGH)
   - bsage import found in skill.py
   - Location: skills/calendar-input/skill.py:3
   - Fix: Remove import, use context.connector() instead

2. Missing SafeModeGuard (CRITICAL)
   - is_dangerous=true skill executed without approval check
   - Location: bsage/core/agent_loop.py:45
   - Fix: Add SafeModeGuard.check() before execution

3. Missing tests (HIGH)
   - Coverage: 65% (threshold: 80%)
   - Missing: bsage/core/scheduler.py lines 78-95
   - Fix: Add unit tests with mocked APScheduler

Cannot approve until resolved.
```

## Common Issues

### Anti-patterns to Catch

1. **Raw os.getenv**:
   ```python
   # Bad
   api_key = os.getenv("LLM_API_KEY")

   # Good
   from bsage.core.config import settings
   api_key = settings.llm_api_key
   ```

2. **bsage import in skill.py**:
   ```python
   # Bad
   from bsage.core.config import settings

   # Good
   async def execute(context):
       config = context.config
   ```

3. **Bypassing SafeModeGuard**:
   ```python
   # Bad
   await skill_runner.run(skill_meta, context)  # No safety check!

   # Good
   if skill_meta.is_dangerous:
       approved = await safe_mode.check(skill_meta)
       if not approved:
           return
   await skill_runner.run(skill_meta, context)
   ```

4. **Dict instead of dataclass**:
   ```python
   # Bad
   return {"name": "...", "category": "...", "is_dangerous": True}

   # Good
   return SkillMeta(name="...", category="...", is_dangerous=True)
   ```

## Final Verification

Before approving:
- [ ] Run `/deploy` checklist
- [ ] All automated checks pass (`ruff`, `pytest --cov`)
- [ ] No critical or high severity issues
- [ ] Code follows BSage patterns
