# voice-live — живой голос бота (отложено решением владельца 12.09)

> **Статус: ОТЛОЖЕНО, не MVP.** Владелец 12.09.2026: «на скорости сильно не заморачивайся,
> я не с этого устройства стримить буду, на другой машине скорость лучше будет».
> Всё установленное работает и лежит; интеграция в эфир — после переезда на целевую машину.
> Активный статус приёмки — [PLAN_TODO.md](../PLAN_TODO.md), здесь — только голосовой трек.

## Что уже готово (сделано 12.09 на Steam Deck)

| Компонент | Где | Состояние |
|---|---|---|
| f5-tts 1.1.22 (клон голоса) | `venv` проекта | установлен, синтезирует (звук чистый, max −0.3 дБ) |
| omnivoice 0.2.1 (клон голоса) | `venv` проекта | установлен, синтезирует; **API отличается от провайдера в боте** (см. «Интеграция») |
| Модели (веса) | `~/.cache/huggingface/` | скачаны: SWivid/F5-TTS, k2-fsa/OmniVoice, charactr/vocos-mel-24khz + whisper для реф-текста |
| Панель омнивойса | `~/Desktop/Омнивойс/start-панель.sh` → localhost:7860 | работает (голая demo-страница — это весь UI пакета) |
| Панель F5 Studio | `venv/bin/f5-tts_infer-gradio` → localhost:7861 | работает, полноценный UI |
| Цепочка в боте | `voice_clones` + `tts_bot_config.provider='xtts'` + `settings.tts_clone_engine='f5tts'` | проверена end-to-end на тестовом сэмпле (приёмочная база `data/live-acceptance/`) |
| Silero (xenia/baya/eugene/aidar) | только демки | ⛔ CC-NC-BY — для эфира нельзя |

## Почему отложено — замеры скорости (Steam Deck CPU)

| Движок | Фраза ~3–4 с | Комментарий |
|---|---|---|
| F5-TTS warm | **255 с** | каждый запрос в боте заново грузит модель (провайдер создаётся per-request) |
| OmniVoice | **~170 с** | измерено с двумя работающими панелями на фоне; на целевой машине перемерить |

Вывод: живой чат локальный клон на Deck не обслуживает. На целевой машине (GPU/нормальный CPU)
перемерить по методике OV-05 (`../omnivoice/IMPLEMENTATION.md`): time-to-first-audio, RTF, RAM.

## Лицензии (проверено 12.09; сылки для личной перепроверки владельцем)

| Движок | Лицензия | Эфир с донатами |
|---|---|---|
| OmniVoice | код Apache-2.0; веса подтверждены владельцем 10.09 (`../omnivoice/LICENSE_REVIEW.md`) | ✅ |
| F5-TTS | веса CC-BY-NC-4.0 — https://huggingface.co/SWivid/F5-TTS | ⛔ некоммерческое |
| Silero | CC-NC-BY — https://github.com/snakers4/silero-models | ⛔ некоммерческое |
| Piper | MIT — https://huggingface.co/rhasspy/piper-voices | ✅ (голоса «дикторские») |
| ElevenLabs | облако, тарифный лист — https://elevenlabs.io/voice-library | ⚠️ по тарифу |
| edge-tts | неофициальный API Microsoft — серая зона ToS | ⚠️ риск прикрытия |

Правило из ревизии 10.09: **смена ревизии весов = повторная проверка license-тега**.

## Что сделать владельцу (чек-лист при переезде на целевую машину)

1. **Сэмпл голоса** (10–30 с чистой речи, wav/mp3, без музыки/шума). Свой голос или
   письменное согласие человека (консент-правило OV-06). Клонить стримеров без согласия —
   риск бана за impersonation, запрещено.
2. **Установить на целевой машине:** python venv → `pip install -r requirements-ml.txt`
   (там omnivoice; f5-tts — опционально) либо точечно `pip install omnivoice`.
3. **Перемерить скорость** обеих панелей на новой машине; выбрать движок эфира.
4. **Сверить license-тег** на https://huggingface.co/k2-fsa/OmniVoice (см. правило выше),
   зафиксировать дату/ревизию в `../omnivoice/LICENSE_REVIEW.md`.
5. **Интеграция в бота** (см. ниже) → прогнать голос через ACCEPT-01-сцену в реальном OBS
   (StartRecord → `ffmpeg -af volumedetect`, виджет `/widget/tts-bot` в сцене).

## Интеграция в бота — заметки на будущее

- Провайдер: `app/tts_engine.py::OmniVoiceProvider` ждёт `OmniVoiceTTS` с
  `.from_pretrained()` / `.synthesize(text, voice=...)` — **такого класса в pip-пакете нет**:
  0.2.1 экспортирует `OmniVoice` (transformers-модуль, `OmniVoice(config, llm)` +
  `create_voice_clone_prompt`), CLI `omnivoice-infer --text --ref_audio --output` работает.
  Нужен адаптер под актуальный API (или пиннуть ревизию репо k2-fsa, как в OV-03).
- Маршрутизация: `_get_provider()` не возвращает omnivoice ни для одного имени провайдера —
  добавить ветку (сейчас: web_speech / piper / xtts→[Coqui|F5] / elevenlabs).
- Готовая цепочка клонов уже есть: `POST /api/voice-clones` (provider='xtts',
  sample_b64) → `voice_clones.sample_path` → `settings tts_clone_engine='f5tts'` →
  per-bot `tts_bot_config.provider='xtts'` → `POST /api/voice-clones/{id}/preview` для прослушки.
- В сцене OBS за звук отвечает источник `/widget/tts-bot` (`tts-chat-overlay` по дизайну
  только показывает ленту текста); «single output» — `tts_audio_output` (пусто = играют все).
- Косяк этой машины, мешавший отладке: browser-источники, созданные через websocket, без
  явного `reroute_audio: true` молчат; web_speech в OBS CEF нежизнеспособен (voices:0).
