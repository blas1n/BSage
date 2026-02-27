---
context: debug
description: Debugging mode - diagnosing and fixing issues in BSage
---

# Debug Context

You are debugging issues in BSage. Systematic diagnosis is key.

## Debugging Workflow

### 1. Gather Information

**What to collect**:
- Error message (full traceback)
- structlog output
- Input that caused error
- Expected vs actual behavior

**Commands**:
```bash
# Run with debug logging
LOG_LEVEL=DEBUG bsage run --skill garden-writer

# Check structured logs
bsage run --skill garden-writer 2>&1 | jq .

# Run specific module in isolation
python -m bsage.core.skill_loader
```

### 2. Reproduce Locally

**Steps**:
1. Isolate the failing component
2. Create minimal reproduction case
3. Run in debugger

```python
# Reproduce in test
@pytest.mark.asyncio
async def test_failing_case(tmp_path):
    loader = SkillLoader(tmp_path / "skills")
    # Create minimal skill structure
    skill_dir = tmp_path / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.yaml").write_text("name: test-skill\n...")
    registry = await loader.load_all()
```

### 3. Common Issue Categories

#### SkillLoader Issues

**skill.yaml not found or invalid**:
```bash
# Check skill directory structure
ls -la skills/*/skill.yaml

# Validate yaml syntax
python -c "import yaml; yaml.safe_load(open('skills/garden-writer/skill.yaml'))"
```

**Missing required fields**:
```python
# Add debug logging to SkillLoader
logger.debug("skill_yaml_parsed", data=data, path=str(yaml_path))
```

#### SkillRunner / execute() Issues

**Import error in skill.py**:
```bash
# Check for bsage imports (forbidden)
grep -r "from bsage\|import bsage" skills/

# Test skill.py in isolation
python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('skill', 'skills/garden-writer/skill.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('Loaded successfully')
"
```

**context object missing method**:
```python
# Check SkillContext interface
from bsage.core.skill_context import SkillContext
print(dir(SkillContext))
```

#### AgentLoop Issues

**ProcessSkill chain not executing**:
```python
# Check rules in skill.yaml
logger.debug("rules_check", skill=name, rules=meta.rules)

# Check LLM fallback
logger.debug("llm_decision", input_skill=name, chosen_skills=process_skills)
```

**Infinite loop in skill chain**:
```python
# Add visited set to detect cycles
visited = set()
for ps_name in process_skills:
    if ps_name in visited:
        logger.error("skill_chain_cycle", skill=ps_name)
        break
    visited.add(ps_name)
```

#### Connector Issues

**Connector not found**:
```bash
# List connected connectors
bsage connector list

# Check credentials
ls -la .credentials/
```

**Authentication failure**:
```python
# Debug connector auth
logger.debug("connector_auth_attempt", connector=name)
try:
    await connector.authenticate()
except Exception as e:
    logger.error("connector_auth_failed", connector=name, error=str(e))
```

#### SafeModeGuard Issues

**Approval not reaching user**:
```python
# Check interface layer binding
logger.debug("safe_mode_request", skill=skill_meta.name, interface=type(self._interface).__name__)
```

**Skill bypassing safety check**:
```bash
# Verify is_dangerous flag
grep "is_dangerous" skills/*/skill.yaml

# Check AgentLoop integration
grep -n "safe_mode\|is_dangerous" bsage/core/agent_loop.py
```

#### GardenWriter Issues

**Notes not appearing in Vault**:
```bash
# Check vault path
echo $VAULT_PATH
ls -la $VAULT_PATH/

# Check directory structure
ls -la $VAULT_PATH/seeds/
ls -la $VAULT_PATH/garden/
ls -la $VAULT_PATH/actions/
```

**Invalid markdown frontmatter**:
```python
# Validate generated note
import yaml
with open(note_path) as f:
    content = f.read()
    # Extract frontmatter
    parts = content.split("---")
    if len(parts) >= 3:
        fm = yaml.safe_load(parts[1])
        print("Frontmatter:", fm)
```

#### Scheduler Issues

**Cron trigger not firing**:
```python
# Debug scheduler jobs
for job in scheduler.get_jobs():
    logger.debug("scheduled_job", id=job.id, next_run=str(job.next_run_time))
```

**APScheduler configuration**:
```bash
# Check timezone
python -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; s = AsyncIOScheduler(); print(s.timezone)"
```

### 4. Debugging Tools

#### Python Debugger

```python
import pdb; pdb.set_trace()

# Async version
breakpoint()  # Works in async context too
```

#### structlog Debug Output

```python
import structlog
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],  # Human-readable in dev
)
```

### 5. Performance Debugging

#### Slow Skill Execution

```python
import time

start = time.time()
result = await skill_runner.run(skill_meta, context)
duration = time.time() - start

logger.info("skill_perf", skill=skill_meta.name, duration_s=duration)
```

#### Slow LLM API

```python
import time

start = time.time()
response = await context.llm.chat(...)
latency_s = time.time() - start

logger.info("llm_perf", latency_s=latency_s, model=settings.llm_model)
```

## Issue Resolution Pattern

### 1. Identify Root Cause

- [ ] Read full error traceback
- [ ] Check structlog output
- [ ] Verify configuration (LOG_LEVEL=DEBUG)
- [ ] Test in isolation

### 2. Fix

- [ ] Implement fix
- [ ] Add test to prevent regression
- [ ] Verify fix locally
- [ ] Check for similar issues in other modules

### 3. Prevent Recurrence

- [ ] Add validation / better error messages
- [ ] Improve logging
- [ ] Document solution
- [ ] Consider retry logic for transient failures

## When Stuck

1. **Check skill.yaml**: Is the configuration correct?
2. **Check context**: Does SkillContext provide the needed interface?
3. **Check Vault**: Is VAULT_PATH set and writable?
4. **Check logs**: Run with LOG_LEVEL=DEBUG
5. **Ask for help**: Describe what you've tried
