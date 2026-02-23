---
description: Security rules for BSage
---

# Security Rules

## CRITICAL: Credential, Data, and Safety Security

### 1. Environment Variables

**NEVER commit secrets to git.**

**ALWAYS use .env files (gitignored):**

```python
# Correct
from bsage.core.config import settings
# settings.anthropic_api_key is auto-loaded from .env via pydantic-settings

# Wrong
API_KEY = "sk-ant-..."  # NEVER hardcode credentials!
```

**Provide .env.example (committed, no real secrets):**

```bash
# .env.example (committed)
ANTHROPIC_API_KEY=sk-ant-...
VAULT_PATH=./vault
SKILLS_DIR=./skills
SAFE_MODE=true
LLM_PROVIDER=claude

# .env (gitignored, actual secrets)
ANTHROPIC_API_KEY=sk-ant-real-key-here
```

### 2. Service Credentials

**NEVER log or expose authentication tokens.**

```python
# Correct
logger.info("credential_loaded", service=name)

# Wrong
logger.info(f"Authenticated with token: {token}")  # NO!
```

**Service credentials stored in `.credentials/` directory (gitignored) via CredentialStore.
SkillRunner auto-injects resolved credentials into `context.credentials` dict:**

```python
# Correct - credentials auto-injected as dict by SkillRunner
creds = context.credentials  # dict[str, Any]

# Wrong - store tokens in plain text
with open("tokens.txt", "w") as f:
    f.write(f"{service}:{token}")  # NEVER!
```

### 3. API Keys in Logs

**NEVER log API keys or secrets.**

```python
# Correct
logger.info("llm_call", provider=settings.llm_provider, model="claude-sonnet-4-20250514")

# Wrong
logger.info(f"Using API key: {settings.anthropic_api_key}")  # NO!
```

### 4. Safe Mode

**BSage의 안전 모델:**

**1차: Skill 설치 여부** — 사용자가 설치하지 않은 Skill은 실행 자체 불가.

**2차: SafeModeGuard**
```python
# is_dangerous=True Skill은 반드시 사용자 승인 필요
if skill_meta.is_dangerous:
    approved = await interface.request_approval(skill_meta)
    if not approved:
        raise SkillRejectedError(f"User rejected execution of '{skill_meta.name}'")
```

**NEVER bypass SafeModeGuard. NEVER skip is_dangerous check.**

### 5. Vault 데이터 경계

**2nd Brain(Vault) 밖으로 절대 데이터가 나가지 않는다.**

```python
# Correct — Vault 내부에서만 읽기/쓰기
note_path = settings.vault_path / "garden" / "ideas" / f"{slug}.md"
if not note_path.resolve().is_relative_to(settings.vault_path.resolve()):
    raise ValueError("Path traversal detected — cannot access outside Vault")

# Wrong — Vault 데이터를 외부로 전송
requests.post("https://external.api/data", json=vault_data)  # NEVER!
```

**예외: OutputSkill을 통한 의도적 동기화만 허용 (git-output, s3-output 등)**

### 6. Input Validation

**Validate all external inputs:**

```python
# Skill 이름 검증
import re

def validate_skill_name(name: str) -> str:
    if not re.match(r'^[a-z][a-z0-9-]*$', name):
        raise ValueError(f"Invalid skill name: {name}. Use lowercase alphanumeric with hyphens.")
    return name
```

### 7. Temporary File Cleanup

**ALWAYS clean up temporary files after processing.**

```python
# Correct
try:
    await skill_runner.run(skill_meta, context)
finally:
    if not keep_tmp:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# Wrong - leave temp files
pass  # tmp files remain
```

### 8. Secure Defaults

**Principle of least privilege:**

- Safe mode ON by default (`SAFE_MODE=true`)
- 사용자가 설치한 Skill만 실행 가능
- API keys scoped to minimum permissions
- No `shell=True` in subprocess calls
- Skill은 `context` 객체를 통해서만 외부 접근

### 9. Error Messages

**NEVER expose credentials in error messages:**

```python
# Correct (user-facing)
raise CredentialNotFoundError("No credentials for 'google-calendar'")

# Correct (logs)
logger.error("credential_load_failed", service=name, exc_info=True)

# Wrong
raise Exception(f"Auth failed with token {token}")  # Exposes secrets!
```

## Verification Checklist

Before every commit:
- [ ] No hardcoded credentials (API keys, tokens)
- [ ] .env.example provided
- [ ] No secrets in logs
- [ ] .credentials/ in .gitignore
- [ ] SafeModeGuard not bypassed
- [ ] Vault path traversal prevented
- [ ] Temp file cleanup implemented
- [ ] No `shell=True` in subprocess calls
- [ ] is_dangerous correctly set on all Skills
