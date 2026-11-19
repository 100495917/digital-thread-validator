# Pull Request

## Summary

<!-- What does this change do, and why? -->

## Linked requirements (REQ-IDs)

<!-- List every requirement this change implements, modifies, or invalidates. -->
<!-- Example: REQ-001, REQ-003 -->

- ...

## Type of change

<!-- Check all that apply. -->

- [ ] Requirement change (added / modified / removed)
- [ ] System model change (block / interface / behavior)
- [ ] Tooling or pipeline change
- [ ] Test change
- [ ] Documentation change
- [ ] Infrastructure or deployment change

## Checklist

- [ ] Requirement IDs are referenced in the summary and/or commit messages
- [ ] The system model is updated when behavior or interfaces change
- [ ] Tests are added or updated and tagged with the relevant `@pytest.mark.req` markers
- [ ] The impact analysis report has been reviewed
- [ ] No secrets, credentials, or private keys are included
- [ ] Documentation is updated where behavior or usage changed
- [ ] Validation passes locally (`mbse validate`)

## Impact analysis

The CI pipeline posts an impact-analysis comment on this pull request, summarizing the affected requirements, model elements, tests, and generated artifacts. Review that comment before merging.
