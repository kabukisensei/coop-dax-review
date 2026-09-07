# Native Windows validation — 2026-09-07

Starting revision: ee64071124289da877d2f570a742858da19d7d62.
Branch: feature/coop-desktop-windows-validation; core.autocrlf=false.
Windows 11 Pro 10.0.26200 x64; Python 3.12.10.

The full native baseline produced 623 passes and one skip: POSIX chmod could not
make a TMDL fixture unreadable on Windows. The regression now holds an exclusive
Windows file handle (CreateFileW with no sharing), producing a real native sharing
violation while checking that the other model and diagnostic remain available.
No system permissions or user files are changed.

Validation from this isolated checkout:
- .venv/Scripts/python.exe -m pytest -q: 624 passed, zero skipped, one pre-existing Click deprecation warning; 13.76s, exit 0.
- .venv/Scripts/python.exe -m ruff check src tests: All checks passed, exit 0.
- .venv/Scripts/python.exe -m ruff format --check src tests: 105 files already formatted, exit 0.

Backup: .backups/windows-20260907/test_regressions.py.bak (ignored).
Logs: ../../outputs/evidence/coop-dax-review-desktop-*-fixed.log.
Source validation does not establish installed Desktop or Power BI acceptance.
No package version, tag, publication, installation, or business workspace changed.
