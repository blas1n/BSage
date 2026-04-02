You are a developer writing E2E tests and fixing API integration.

Read .agent/tasks.json and select the highest-priority task where passes is false.

## E2E Test Guidelines
- Tests are the source of truth — code must match tests, not the other way around
- Use page.route() to mock ALL API responses 
- Test that Stitch design elements render: Material Symbols icons, uppercase tracking-widest labels, rounded-xl cards
- Test navigation between all pages via sidebar
- Test key interactions: modals, search, filters, buttons
- Use getByRole/getByText selectors
- If a test fails because the code is wrong, FIX THE CODE not the test

## API Fix Guidelines  
- If frontend gets 405: wrong HTTP method (GET vs POST) or wrong endpoint path
- If frontend gets 500: backend error — check the API endpoint exists and works
- Frontend API calls must match backend endpoint definitions exactly

After implementation:
1. Verify: pnpm build && npx playwright test --reporter=line
2. If passes: git commit (no Co-Authored-By)
3. Update .agent/tasks.json: set passes to true
4. Append to .agent/progress.txt

IMPORTANT: Only work on ONE task per invocation.
