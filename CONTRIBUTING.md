# Contributing

1. Create a focused branch from `main`.
2. Use Python 3.11 and install `requirements-dev.lock`.
3. Add deterministic tests for externally observable behavior.
4. Run `./scripts/quality.sh`.
5. Open a pull request using the repository template.

Never commit credentials, broker or portfolio data, generated reports, payment
records, user data, or provider responses containing private information. Do
not add real order placement. Update prompt/model version identifiers and the
research evaluation cases when AI behavior changes materially.
