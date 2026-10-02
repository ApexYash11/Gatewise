# What this changes

<!-- One paragraph. What is different after this pull request? -->

## Why

<!-- The problem being solved. Link the issue if there is one: Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New capability
- [ ] Refactor or internal cleanup
- [ ] Documentation

## Checklist

- [ ] `pytest` passes locally (248 tests, no network needed).
- [ ] New behaviour has a test; a bug fix has a test that fails without it.
- [ ] Tests stub the **network boundary**, not the model's judgement. No test hard-codes "this PR is high risk".
- [ ] New provider failure modes are covered: timeout, rate limit, authentication, network error, malformed response, missing answer.
- [ ] If a rubric or question definition changed, the version in `packages/decisions/questions/pull_request.yaml` was **bumped**. Changing a rubric silently changes the meaning of every stored answer.
- [ ] No secret, `.env` file, API key, token, private key, or local `*.db` is included.
- [ ] No demo video or screenshot is committed; those belong in the gitignored `demo/` directory.
- [ ] Documentation updated if behaviour or setup changed.

## Security note

<!-- Required if this touches context building, webhook verification, credential handling, or action execution. -->

- [ ] This change does not let untrusted pull request text reach decision instructions.
- [ ] This change does not convert a provider failure into a default decision.
- [ ] This change does not log or return a credential value.

## Verification

<!-- How you tested it. Include the command and its output. -->