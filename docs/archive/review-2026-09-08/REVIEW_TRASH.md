# REVIEW_TRASH — A: кандидаты на cleanup

> Решения владельца приняты 08.09; исполнение pending. Каждый кандидат: отдельный commit,
> caller/reference proof, профильный focused test и повторная генерация `REVIEW_COVERAGE.md`.

| ID | Sev / confidence / owner | Path, provenance, evidence | Impact / action | Test / rollback / decision |
|---|---|---|---|---|
| A-001 🔶 | P3 / high / owner | `get-pip.py` (~2.2 MB), vendored pip bootstrap; repository caller не найден. | Owner decision: DELETE после setup/caller proof; будущий offline setup — versioned wheelhouse, не bootstrap snapshot. | grep + clean setup; isolated delete commit. |
| A-002 🔶 | P3 / medium / owner | `shot_mascot.png`, unreferenced historical screenshot. | Owner decision: DELETE после reference/provenance scan. | reference/history scan; isolated delete commit. |
| A-003 🔶 | P3 / high / frontend owner | `templates/index_v10_backup.html`, unreachable: `/` использует `index.html` (`app/routes.py:152`). | Owner decision: DELETE; git history является backup. | route/template grep + focused panel tests. |
| A-004 🔶 | P3 / high / widgets owner | `templates/obs_tts_widget.html`; `/obs/tts` обслуживается `widgets/tts-raw` (`app/routes.py:2463`). | Owner decision: DELETE только файл; public `/obs/tts` и canonical renderer сохранить. | legacy URL sweep + TTS tests. |
| A-005 🔶 | P3 / high / ops owner | `start_v12.sh`: трёхстрочный alias к `start.sh --no-browser`, владелец им не пользуется. | Owner decision: DELETE после repository/local shortcut proof; `start.sh --no-browser` остаётся canonical. | start-script grep/subprocess. |
| A-006 🔶 | P3 / high / frontend owner | `scripts/p5_split_app_js.py`: one-time structural rewrite helper, active caller отсутствует. | Owner decision: DELETE после caller proof; не запускать на current tree. | grep + node/focused app split guards. |
| A-007 🔶 | P3 / medium / owner | `scripts/p5_split_routes.py`, `scripts/panel_review_render.py`: разные historical tools без operational caller. | Owner decision: DELETE route splitter; ARCHIVE review generator вместе с `docs/panel_review_data.json` и historical output. | identify links/input/output + secret scan; separate delete/archive commits. |
