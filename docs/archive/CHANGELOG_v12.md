# CHANGELOG v12

> Ops-сессия + общий план v12. Полные планы: PLAN_ALL_IN_ONE.md, OPS_PLAN.md.

## P0 — надёжность и обратная связь

- **Health-состояния ботов** (§5.1): connecting/online/error/offline, событие в панель
  и per-bot логи; красный бейдж с причиной и кнопкой переподключения в карточке.
- **Причины отказа отправки** (§5.2): send_message_detailed → machine-readable
  reason (`oauth_expired`, `network_error`, `cooldown`, `channel_not_connected`, …)
  + человекочитаемый текст в панели.
- **Триггеры**: привязка к каналу, счётчик срабатываний, включение/выключение,
  last_fired_at.

## §25 — прочее

- widgets/ — папка виджетов (свой план: WIDGETS_PLAN.md).
- Кастомные AI-провайдеры (§25.4): таблица custom_providers, CRUD в панели,
  генерация через `custom:<name>`.
- Общие факты о зрителях (§25.3): shared_chatter_facts.
- AI-фидбэк (§25.5): bot_response_feedback, 👍/👎 в панели.

## Эксплуатация (OPS_PLAN, начало)

- instance-lock (§2): один процесс на бота (панель ↔ standalone не конфликтуют).
- bootstrap (§2): общий wiring ботов для панели и standalone.
- Bot Files (§1): HTTP-роуты над per-bot папками, лимиты, path-traversal тесты.
