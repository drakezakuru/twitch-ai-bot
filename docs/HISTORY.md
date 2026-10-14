# История проекта и документации

> Короткий индекс завершённых этапов. Это не план. Полные старые материалы находятся в
> [`archive/`](archive/) и локальной git-истории.

## Как восстановить старый документ

```bash
git log --all --oneline -- <путь>
git show <commit>:<путь>
```

Не используйте `git restore/reset/checkout -- <file>` в рабочем дереве: для просмотра достаточно
`git show`.

## Основные этапы

- **28–31.08.2026:** базовая панель, роли, moderation, Stream/TTS/brain планы и параллельные сессии.
- **03.09.2026:** owner survey widgets; удалены/retired шесть widget implementations с сохранением
  public compatibility URLs; объединены event/top-donator/emoji families.
- **04–05.09.2026:** fake-local Track 6, scoped widget/API state, widget previews, TTS families,
  moderation console, sound/media/song/polls/predictions contracts.
- **06.09.2026:** полный repository audit: security, runtime task ownership, account/channel ownership,
  dependency lock, stale helpers и documentation ledgers.
- **08.09.2026:** C-010 source-marker tests заменены production Node VM behavior tests; owner decisions
  записаны; `68bdd2c` вернул passwordless localhost; `b9d693a`/`a4a8483` создали canonical docs и
  единый план; `c10d9ce` сократил module map; `f743274` заархивировал review evidence;
  `2e65bd0` удалил семь byte-identical root-дубликатов.
- **09.09.2026:** Widget Bus и protected moderator-media изолированы по Twitch channel; donation
  providers, effects, persistent dedup и local webhook bridge переведены на exact account/channel scope;
  API errors получили safe structured envelope и v13 frontend compatibility, legacy role mutation удалена,
  TTS defaults стали read-only effective response; Media Share получил persisted external-provider
  disclosure и честные YouTube/queue/reconnect states; неиспользуемый vendored `get-pip.py` удалён после
  двух независимых caller/reference searches, canonical setup остаётся на dependency manifests.

## Audit snapshots

Review documents `REVIEW_*`, `FINDINGS_0409`, `APP_JS_MAP`, `AUDIT_PLACEMENT` и related research были
рабочими ledger-файлами полного аудита. После переноса открытых пунктов в единственный
`PLAN_TODO.md` они заморожены в `docs/archive/review-2026-09-08/` (`f743274`).

Последний reproducible coverage snapshot перед консолидацией документации:

- 581/581 tracked paths classified;
- 1453/1453 public Python symbols classified;
- generator: `scripts/build_review_inventory.py`;
- источник: прежний `docs/REVIEW_COVERAGE.md`.

Coverage snapshot доказывает полноту конкретного audit pass, но не является вечным active backlog.

## Исторические группы документов

В `docs/archive/` сохраняются:

- старые `PLAN*`, session и feature plans;
- changelog v11–v14;
- panel review/checklist/smoke evidence;
- audit feedback и comparison documents;
- handoff/recovery notes.

Точные root-дубли удаляются после проверки hashes; уникальный архивный оригинал остаётся.

## Активная документация после консолидации

- `README.md` — как запустить и использовать;
- `AGENTS.md` — как безопасно менять код;
- `PLAN_TODO.md` — что делать дальше;
- `FILE_ZONES.md` — компактная карта модулей;
- `docs/PRODUCT_RULES.md` — жёсткие продуктовые правила;
- `docs/DECISIONS.md` — почему выбраны контракты;
- `docs/ARCHITECTURE.md` — как устроена система;
- `docs/specs/` — отдельные future specifications;
- `widgets/README.md` — widget inventory.
