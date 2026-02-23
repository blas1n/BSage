---
name: core-patterns
description: BSage Core Engine 구현 패턴 및 데이터 흐름
---

# Core Patterns Skill

## 실행 흐름

```
Scheduler (cron) ─── input skill ──→ AgentLoop.on_input(raw_data)
                 └── process skill → 직접 실행 + action 로그

AgentLoop.on_input(raw_data)
        ↓
GardenWriter → /seeds 저장
        ↓
trigger 매칭 → on_input process skill 목록 결정
        ↓
LLM 판단 → on_demand process skill 추가
        ↓
SafeModeGuard.check()
        ↓ (승인)
SkillRunner.run(meta, context)
        ↓
GardenWriter → /actions 저장
        ↓
SyncManager.notify() → output skill 실행
```

## SkillMeta (skill_loader.py)

```python
@dataclass
class SkillMeta:
    name: str
    version: str
    category: str              # input / process / output
    is_dangerous: bool
    description: str
    author: str = ""
    entrypoint: str | None = None
    trigger: dict | None = None
    credentials: dict | None = None
    notification_entrypoint: str | None = None  # 양방향 채널

    # YAML-only skill fields
    read_context: list[str] = field(default_factory=list)
    output_target: OutputTarget | None = None  # OutputTarget enum (GARDEN, SEEDS)
    output_note_type: str = "idea"
    system_prompt: str | None = None
    output_format: str | None = None
```

## AgentLoop 패턴

```python
class AgentLoop:
    async def on_input(self, skill_name: str, raw_data: dict) -> list[dict]:
        """InputSkill 결과 수신 → trigger 매칭 → 실행."""
        # 1. seeds에 원시 데이터 저장
        await self._garden_writer.write_seed(skill_name, raw_data)

        # 2. trigger.type == on_input인 process skill 필터
        triggered = self._find_triggered_skills(skill_name)

        # 3. on_demand skill 중 LLM 판단
        on_demand = await self._decide_on_demand_skills(skill_name, raw_data)

        # 4. 실행 (SafeMode 체크 포함)
        for meta in triggered + on_demand:
            approved = await self._safe_mode_guard.check(meta)
            if not approved:
                continue
            context = self.build_context(input_data=raw_data)
            result = await self._skill_runner.run(meta, context)
            summary = json.dumps(result, default=str)
            await self._garden_writer.write_action(meta.name, summary)

    def _find_triggered_skills(self, source_name: str) -> list[SkillMeta]:
        """trigger.type == on_input이고 sources 조건에 맞는 process skill."""
        result = []
        for meta in self._registry.values():
            if meta.category != "process" or not meta.trigger:
                continue
            if meta.trigger.get("type") != "on_input":
                continue
            sources = meta.trigger.get("sources")
            if sources is None or source_name in sources:
                result.append(meta)
        return result
```

## SkillRunner 패턴

```python
class SkillRunner:
    async def run(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        # 1. credential 자동 주입
        await self._auto_inject_credentials(skill_meta.name, context)

        # 2. entrypoint 유무에 따라 실행
        if skill_meta.entrypoint:
            return await self._run_python(...)
        else:
            return await self._run_llm(skill_meta, context)

    async def run_notify(self, skill_meta, context) -> dict:
        """notification_entrypoint 실행 (양방향 채널)."""
        return await self._run_entrypoint(
            skill_meta.name, skill_meta.notification_entrypoint, context
        )

    async def _run_entrypoint(self, skill_name, entrypoint, context) -> dict:
        """공통 entrypoint 로딩 + 실행 (run, run_notify 공유)."""
        module_file, func_name = entrypoint.split("::")
        module = load_module(self._skills_dir / skill_name / module_file)
        return await getattr(module, func_name)(context)

    async def _run_llm(self, skill_meta, context) -> dict:
        """YAML-only 3단계 파이프라인: GATHER → LLM → APPLY."""
        vault_context = await self._gather_vault_context(skill_meta.read_context, context)
        system, messages = self._build_messages(skill_meta, vault_context, context.input_data)
        response = await context.llm.chat(system=system, messages=messages)
        return await self._apply_output(skill_meta, context, response)
```

## Scheduler 패턴

```python
class Scheduler:
    def register_triggers(self, registry: dict[str, SkillMeta]) -> None:
        """input, process 모두 cron trigger 등록 가능."""
        for name, meta in registry.items():
            if not meta.trigger or meta.trigger.get("type") != "cron":
                continue
            if meta.category == "input":
                callback = self._on_input_trigger   # run → on_input
            elif meta.category == "process":
                callback = self._on_process_trigger  # run → write_action
            else:
                continue
            self._scheduler.add_job(callback, CronTrigger(...), args=[name])
```

## NotificationRouter (양방향 채널)

```python
class NotificationRouter:
    """input skill의 notification_entrypoint를 통해 알림 전달."""

    def setup(self, registry, skill_runner, context_builder):
        """registry에서 notification_entrypoint 있는 skill 자동 발견."""
        self._skills = [m for m in registry.values() if m.notification_entrypoint]

    async def send(self, message: str, level: str = "info"):
        for meta in self._skills:
            ctx = self._context_builder(input_data={"message": message, "level": level})
            ctx.notify = None  # 재귀 방지
            await self._skill_runner.run_notify(meta, ctx)
```

## SyncManager + Output Skill

```python
class SyncManager:
    def register_output_skills(self, skills, skill_runner, context_builder):
        """output 카테고리 skill 등록."""

    async def notify(self, event: WriteEvent) -> None:
        # 1. 기존 SyncBackend 호출 (하위 호환)
        for backend in self._backends.values():
            await backend.sync(event)
        # 2. output skill 실행
        for meta in self._output_skills:
            context = self._context_builder(input_data=event_data)
            await self._skill_runner.run(meta, context)
```

## CredentialStore 패턴

```python
class CredentialStore:
    """JSON 파일 기반 credential 저장/로드."""

    async def get(self, name: str) -> dict[str, Any]:
        """name.json에서 credential 로드. 없으면 CredentialNotFoundError."""

    async def store(self, name: str, data: dict[str, Any]) -> None:
        """name.json으로 credential 저장."""

    def list_services(self) -> list[str]:
        """저장된 credential 목록 반환."""
```

## Critical Rules

1. **Skill은 자기 완결적 플러그인** — 직접 의존 없음, trigger로 반응 선언
2. **trigger 매칭이 실행을 결정** — rules 없음, 각 skill이 자기 trigger 선언
3. **is_dangerous 체크는 건너뛸 수 없다** — SafeModeGuard 우회 금지
4. **Vault 밖으로 데이터 유출 없음** — OutputSkill을 통한 의도적 동기화만 허용
5. **외부 서비스 연결은 Skill이 자체 처리** — credential은 자동 주입
6. **유저 알림은 context.notify 경유** — input skill의 역방향(notification_entrypoint)으로 전달
