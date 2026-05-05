"""BSage demo backend module.

BSage uses SQLite + an Obsidian-like Vault (Markdown files). Demo:
- Pre-seeded vault at ``/app/vault-demo`` with 20 sample notes,
  knowledge graph entities, and 3 plugin events
- SAFE_MODE forced ON in demo (no plugin outbound)
- Per-visitor "tenant" is a directory namespace under vault-demo
- JWT issued via /api/v1/demo/session
"""
