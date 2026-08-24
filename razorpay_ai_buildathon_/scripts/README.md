# scripts/

Developer utilities directory.

Scripts added here in future phases:

| Script | Phase | Purpose |
|---|---|---|
| `seed_db.py` | 2 | Load synthetic data into PostgreSQL |
| `generate_data.py` | 2 | Run the synthetic dataset generator |
| `run_benchmark.py` | 3 | Run full reconciliation evaluation |
| `export_audit.py` | 3 | Export audit trail to JSON/CSV |

All scripts must:
- use `python scripts/<name>.py` invocation
- read configuration from environment variables
- never hardcode credentials
- never modify production data
