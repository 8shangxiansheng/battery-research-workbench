# Vibe Coding Contract — Battery Research Workbench V1.1

All AI coding agents must obey:

1. Read `README.md`, `docs/development-plan.md`, and relevant data contracts first.
2. One prompt / PR should solve one BRW task.
3. Write or confirm acceptance tests before implementation.
4. Never modify `data/raw/`.
5. Never infer meanings for `unknown_*` ultrasonic metadata.
6. Never use Cycle as the primary cross-file synchronization key.
7. Synchronization order is:
   Battery/Experiment → DataAsset → absolute timestamp → nearest electrical record → Cycle/Step mapping.
8. Persist `sync_error_s`; never hide alignment uncertainty.
9. One Experiment may contain multiple XLSX/TXT assets.
10. Filename is not authoritative identity; manifests/IDs are.
11. Scientific algorithms live in deterministic modules, never only inside Agent prompts.
12. Parser changes require golden/integration tests.
13. Signal algorithms require synthetic validation when feasible.
14. Missing sampling frequency must block absolute TOF/frequency reporting.
15. ML splitting must group by Battery, not random rows.
16. Do not weaken tests merely to make CI pass.
17. Every completed task must report:
    - files changed
    - behavior changed
    - tests run/results
    - known limitations
