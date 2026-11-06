## What & why

## How it was tested
- [ ] `make check` passes locally
- [ ] New behaviour has tests (domain logic: unit; endpoints: integration)

## Checklist
- [ ] No secrets, keys or `.env` content in the diff
- [ ] Migrations added for model changes (`alembic revision --autogenerate`) and reviewed
- [ ] Prompt changes bump `PROMPT_VERSION` and keep the verifier and pipeline tests green
- [ ] Docs / README updated if behaviour or config changed
