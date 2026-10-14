# OmniVoice PoC — порядок реализации

> Этапы будущей работы; активный статус — только в [PLAN_TODO.md](../PLAN_TODO.md).
> Каждый завершённый этап: focused tests, `git diff --check`, маленький коммит.

## OV-00. Требования и границы — ✅ готово
- Экспериментальный optional provider; панель/TTS-transport не зависят от установки.
- Зафиксировано в PLAN_TODO (секция PoC) и README.

## OV-01. License review — ✅ готово
- [LICENSE_REVIEW.md](LICENSE_REVIEW.md). Веса — не подтверждены; gate не снят.

## OV-02. Provider и fallback — ✅ готово (fake-QA)
- `OmniVoiceProvider` в `app/tts_engine.py`: lazy import в worker-thread, license gate,
  отсутствие пакета → предупреждение и fallback на Piper/Web Speech.
- Тест: `tests/test_tts_core_transport.py::test_omnivoice_provider_is_license_gated_and_falls_back`.

## OV-03. Закрепление версий и метрик загрузки — ⏳ установка на устройстве владельца
- Зафиксировать проверенные revision: repo commit, pip-версия, model ревизия.
- Показать в UI размер загрузки и свободное место до ручной установки через `--ml`.
- Измерение размеров — через HF API при установке на устройстве владельца; скачивание
  весов в панельную песочницу не выполняется.

## OV-04. Изоляция runtime под нагрузкой — частично ✅
- Lazy load и отказ без блокировки панели покрыты fake-QA.
- Осталось: health/`paused`/cancel/timeout/shutdown под реальной загрузкой
  (только на целевом устройстве владельца, после снятия gate).

## OV-05. Real-device benchmark RU/EN/UA — ⏳ на устройстве владельца
- time-to-first-audio, end-to-end latency, RTF, RAM/VRAM, качество клона, границы sentence chunks.
- True streaming не заявлять.

## OV-06. Voice sample consent — ⏳ при первой настройке клонирования
- Для клонирования: подтверждение права/согласия на голос, локальное хранение samples,
  понятное удаление, запрет неявного переиспользования между ботами/каналами.

## Gate (обновлено 10.09)
- License gate весов снят владельцем 10.09.2026 (LICENSE_REVIEW.md).
- Production-решение — после измерений на целевом устройстве (OV-05); до этого OmniVoice
  не заменяет существующие providers и остаётся experimental.
