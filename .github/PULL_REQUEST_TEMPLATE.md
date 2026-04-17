## Summary

<!-- What does this PR change, and why? -->

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation / tooling only

## Related issues

<!-- "Fixes #123" or "Related to #456" -->

## Test plan

<!-- How did you verify the change? -->
- [ ] Ran the app locally and exercised the affected feature
- [ ] `python3 -m pytest tests/` passes
- [ ] `python3 -m py_compile` across changed Python files
- [ ] `node --check` on changed JS files
- [ ] Manual browser test (if UI change)

## Checklist

- [ ] I have read `CONTRIBUTING.md`
- [ ] No secrets, tokens or customer data are included
- [ ] No premium WordPress plugins added under `docker-template/`
- [ ] New routes are protected with `@login_required` or `@admin_required`
- [ ] `subprocess` calls use argument lists (no `shell=True` with interpolation)
- [ ] SQL identifiers are validated; values are escaped or parameterised
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` (for user-facing changes)
