# Skill System Rules

## CRITICAL: Skill 설계 및 구현 규칙

### 1. Skill 포맷

**모든 Skill은 `skills/` 디렉토리에 독립 폴더로 존재한다.**

```
skills/
├── garden-writer/
│   ├── skill.yaml      # 필수 — 메타데이터
│   └── skill.py        # 선택 — 코드 실행 필요 시
├── calendar-input/
│   ├── skill.yaml
│   └── skill.py
└── weekly-digest/
    └── skill.yaml      # yaml only — LLM 지시만으로 처리
```

### 2. skill.yaml 포맷

```yaml
# 필수
name: string                    # lowercase + hyphens (^[a-z][a-z0-9-]*$)
version: string                 # semver
category: input | process | output
is_dangerous: bool
description: string             # LLM 판단에도 사용됨

# 선택
author: string
entrypoint: string              # "skill.py::execute" (없으면 YAML-only)
notification_entrypoint: string # "skill.py::notify" (양방향 채널 시)

# Trigger — 각 skill이 자기 trigger 선언
trigger:
  type: cron | webhook | on_input | write_event | on_demand
  schedule: string              # cron일 때
  sources: list[string]         # on_input일 때 (특정 input만 필터)
  hint: string                  # on_demand일 때 (LLM 가이드)

# Credentials (초기 설정 시 사용)
credentials:
  setup_entrypoint: string      # 커스텀 설정 로직 (OAuth 등)
  fields:                       # CLI 프롬프트 기반 설정
    - name: string
      description: string
      required: bool

# YAML-only 강화 (entrypoint 없을 때 사용)
read_context: list[string]      # Vault 읽기 경로
output_target: garden | seeds   # 결과 저장 위치
output_note_type: string        # garden note type (default: idea)
output_format: json             # JSON 출력 요청
system_prompt: string           # LLM system prompt 오버라이드
```

**NEVER 누락해서는 안 되는 필드:**
- `name`, `version`, `category`, `is_dangerous`, `description`

### 3. 카테고리 정의

| 카테고리 | 역할 | 트리거 예시 |
|----------|------|------------|
| **input** | 외부 데이터 수신 | cron, webhook |
| **process** | 판단 + 행동 (분석, 변환, 메시지 발송 등) | on_input, cron, on_demand |
| **output** | vault → 외부 기계적 동기화 | write_event |

- 세 카테고리는 **독립적** — input → process → output 순차 파이프라인이 아님
- Process는 input 없이도 독립 실행 가능 (cron, on_demand)

### 4. Trigger 시스템

**각 Skill은 자기 trigger를 선언한다. 직접 의존(rules) 없음.**

| type | 대상 | 동작 |
|------|------|------|
| `cron` | input, process | 스케줄 기반 자동 실행 |
| `webhook` | input | HTTP 요청 수신 시 실행 |
| `on_input` | process | Input 결과 도착 시. `sources`로 필터 가능 |
| `write_event` | output | Vault 쓰기 발생 시 자동 |
| `on_demand` | process | LLM 판단 or 사용자 요청. `hint`로 가이드 |

trigger 없는 process = `on_demand`로 간주 (LLM이 description 보고 판단).

```yaml
# 예시: 모든 input에 반응
name: garden-writer
category: process
trigger:
  type: on_input

# 예시: 특정 input에만 반응
name: insight-linker
category: process
trigger:
  type: on_input
  sources: [calendar-input]

# 예시: process도 cron 가능
name: weekly-digest
category: process
trigger:
  type: cron
  schedule: "0 9 * * MON"
```

### 5. skill.py 규칙

**순수 Python. `bsage` 패키지 import 금지.**

```python
# Correct — Skill이 자체적으로 API 연결 처리
async def execute(context):
    creds = context.credentials
    events = await fetch_calendar_events(creds)
    await context.garden.write_seed("calendar", {"events": events})
    return {"collected": len(events)}

# Wrong — bsage import 사용
from bsage.core.config import settings  # NO!
```

**규칙:**
- 진입점: `execute(context)` 함수 고정 (async)
- `context` 객체를 통해서만 외부 접근
- 표준 라이브러리 + PyPI 패키지만 사용
- `bsage` 내부 모듈 직접 import 금지
- 외부 서비스 연결은 Skill이 자체적으로 처리

### 6. SkillContext 인터페이스

Skill은 `context` 객체를 통해서만 Core Engine과 소통한다.

```python
# context가 제공하는 인터페이스
context.credentials                 # dict[str, Any] — 자동 주입된 credential
context.garden.write_seed(...)      # seeds/ 쓰기
context.garden.write_garden(...)    # garden/ 쓰기
context.garden.write_action(...)    # actions/ 로그
context.garden.read_notes(...)      # 기존 노트 읽기
context.llm.chat(...)               # LLM API 호출
context.config                      # Skill 설정값
context.logger                      # structlog 로거
context.input_data                  # 입력 데이터 (on_input 시)
context.notify                      # NotificationInterface (유저 알림)
```

### 7. Credential 시스템

**credential name = skill name** 컨벤션.

```yaml
# skill.yaml에 선언
credentials:
  fields:
    - name: bot_token
      description: "Telegram Bot API token"
      required: true
```

- `bsage setup <skill-name>` CLI로 초기 설정
- 실행 시 `context.credentials`에 자동 주입 (SkillRunner가 CredentialStore에서 resolve)
- `.credentials/` 디렉토리에 JSON으로 저장 (gitignored)

### 8. YAML-Only Skill (선언적 파이프라인)

entrypoint 없는 process skill은 3단계 파이프라인으로 실행:

**GATHER → LLM → APPLY**

1. **GATHER**: `read_context` 경로에서 Vault 노트를 읽어 컨텍스트 구성
2. **LLM**: system prompt + vault context + input_data로 LLM 호출
3. **APPLY**: `output_target`에 따라 결과를 Vault에 저장

```yaml
# 예시: weekly-digest (YAML-only)
name: weekly-digest
version: 1.0.0
category: process
is_dangerous: false
description: Generate a weekly digest from recent garden notes
trigger:
  type: cron
  schedule: "0 9 * * MON"
read_context:
  - garden/idea
  - garden/insight
output_target: garden
output_note_type: insight
output_format: json
system_prompt: |
  Analyze the provided notes and create a weekly summary.
```

- `system_prompt` 오버라이드해도 vault 데이터는 항상 user message로 주입됨
- `output_format: json` → LLM에 JSON 출력 지시 + 자동 파싱

### 9. context.notify — 유저 알림 (양방향 채널)

Process skill이 유저에게 알림 보낼 때 직접 메신저 API 호출하지 않는다.
`context.notify.send()` 사용 — `NotificationRouter`가 채널을 자동 선택.

**알림 채널 = input skill의 역방향.** 별도 output skill 불필요.

```yaml
# skills/telegram-input/skill.yaml
name: telegram-input
category: input
trigger:
  type: webhook
entrypoint: skill.py::execute              # 수신 (input)
notification_entrypoint: skill.py::notify  # 발신 (역방향)
credentials:
  fields:
    - name: bot_token
    - name: chat_id
```

```python
# skills/telegram-input/skill.py

async def execute(context):
    """수신: Telegram → Vault (input 방향)."""
    creds = context.credentials
    messages = await poll_telegram(creds)
    await context.garden.write_seed("telegram", {"messages": messages})
    return {"collected": len(messages)}

async def notify(context):
    """발신: Vault → Telegram (역방향)."""
    creds = context.credentials
    msg = context.input_data["message"]
    await send_telegram_message(creds["bot_token"], creds["chat_id"], msg)
    return {"sent": True}
```

**흐름:**
```
context.notify.send("msg")
  → NotificationRouter.send()
  → registry에서 notification_entrypoint 있는 skill 자동 발견
  → skill_runner.run_notify(meta, ctx) — skill.py::notify 실행
```

- `NotificationRouter.setup(registry, ...)` 시 자동 발견 — 별도 등록 불필요
- 같은 credential 재사용 (같은 bot_token으로 수신 + 발신)
- 알림 skill의 `context.notify = None` (재귀 방지)

**process skill에서 사용:**
```python
async def execute(context):
    if context.notify:
        await context.notify.send("프로젝트 'X'가 12일째 방치됨")
```

### 10. is_dangerous 규칙

**외부 세계에 부작용을 발생시키는 Skill은 반드시 `is_dangerous: true`.**

```yaml
# Dangerous — 외부에 영향
calendar-writer:    is_dangerous: true   # 캘린더 일정 등록
email-sender:       is_dangerous: true   # 이메일 발송
telegram-sender:    is_dangerous: true   # 메시지 발송

# Safe — Vault 내부 작업만
garden-writer:      is_dangerous: false  # 마크다운 정리
insight-linker:     is_dangerous: false  # 노트 연결 발견
weekly-digest:      is_dangerous: false  # 리포트 생성
```

**SafeModeGuard가 `is_dangerous: true` Skill 실행 전 반드시 사용자 승인을 요청한다.**

### 11. GardenWriter 쓰기 규칙

| 디렉토리 | 누가 쓰는가 | 내용 |
|---|---|---|
| `seeds/` | InputSkill 실행 후 | 원시 수집 데이터 |
| `garden/` | ProcessSkill 실행 후 | 정리된 지식 노트 |
| `actions/` | 모든 Skill 실행 후 | 에이전트 행동 로그 |

**ALWAYS use frontmatter:**
```markdown
---
type: idea
status: growing
source: calendar-input
captured_at: 2026-02-22
related: [[BSage]]
---
```

## Verification Checklist

Skill 구현 전:
- [ ] skill.yaml에 필수 필드 모두 존재
- [ ] category: input / process / output 중 하나
- [ ] trigger 적절히 설정
- [ ] is_dangerous 적절히 설정
- [ ] skill.py에서 bsage import 없음
- [ ] execute(context) 진입점 사용
- [ ] 외부 서비스는 Skill 내부에서 자체 처리
- [ ] GardenWriter로 적절한 디렉토리에 쓰기
- [ ] 테스트에서 context mock 사용
