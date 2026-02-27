---
name: test
description: Run tests with coverage verification
---

# Test Command

Run tests for a module or the entire project with coverage requirements.

## Usage

```
/test [module-name]
```

## What This Does

1. **Run tests** for specified module or all modules
2. **Check coverage** (minimum 80%)
3. **Report failures** with actionable feedback
4. **Verify mocks** for external APIs

## Implementation

### Single Module

```bash
# Run tests for core module
pytest bsage/tests/test_skill_loader.py --cov=bsage.core --cov-report=term-missing

# Run tests for garden module
pytest bsage/tests/test_garden_writer.py --cov=bsage.garden --cov-report=term-missing
```

### All Modules

```bash
# Run all tests with coverage
pytest bsage/tests/ --cov=bsage --cov-report=term-missing --cov-fail-under=80
```

### With Lint

```bash
# Code quality + tests
ruff check bsage/ && pytest bsage/tests/ --cov=bsage --cov-fail-under=80
```

## Coverage Requirements

- **All modules**: >= 80%
- **Core modules** (config, exceptions, skill_loader): >= 90%
- **AgentLoop / Scheduler**: >= 80%

## Mock Verification

Ensure all external APIs are mocked:

```bash
# Check for unmocked API calls (should be empty in production code)
grep -r "litellm\.acompletion\b" bsage/ | grep -v "test\|llm.py"
grep -r "AsyncIOScheduler()" bsage/ | grep -v "scheduler.py\|test"
```

## Output

The command should report:
- Tests passed/failed
- Coverage percentage per module
- Uncovered lines
- Missing mocks (if any real API calls found)

## Example

```bash
$ /test

Running BSage tests...

ruff check bsage/  OK (no issues)

============================= test session starts ==============================
bsage/tests/test_config.py ..........                [100%]
bsage/tests/test_skill_loader.py ........            [100%]
bsage/tests/test_skill_runner.py ........            [100%]
bsage/tests/test_skill_context.py ......             [100%]
bsage/tests/test_agent_loop.py ..........            [100%]
bsage/tests/test_scheduler.py ......                 [100%]
bsage/tests/test_safe_mode.py ........               [100%]
bsage/tests/test_connector_manager.py ......         [100%]
bsage/tests/test_garden_writer.py ........           [100%]
bsage/tests/test_vault.py ......                     [100%]

---------- coverage: platform linux, python 3.11.x -----------
Name                                    Stmts   Miss  Cover
------------------------------------------------------------
bsage/core/config.py                       18      0   100%
bsage/core/exceptions.py                   12      0   100%
bsage/core/skill_loader.py                 45      3    93%
bsage/core/skill_runner.py                 38      4    89%
bsage/core/skill_context.py                22      1    95%
bsage/core/agent_loop.py                   52      5    90%
bsage/core/scheduler.py                    35      4    89%
bsage/core/safe_mode.py                    18      1    94%
bsage/connectors/manager.py                28      3    89%
bsage/garden/writer.py                     42      4    90%
bsage/garden/vault.py                      25      2    92%
------------------------------------------------------------
TOTAL                                     335     27    92%

============================== 38 passed in 5.12s ==============================

OK Coverage: 92% (threshold: 80%)
OK All tests passed
```
