# OmniVoice PoC — multilingual local TTS / voice clone

> Experimental optional provider. Piper/Web Speech и core-панель **не зависят** от его установки.
> Статус реализации: offline-часть готова, веса не загружены — активный статус в
> [PLAN_TODO.md](../PLAN_TODO.md), раздел «OmniVoice PoC».

Источник: [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) — 600+ языков, zero-shot TTS,
voice clone, voice design; заявленный RTF до 0.025.

## Что уже сделано (offline)

| Пункт | Статус |
|---|---|
| License review (код / tokenizer-реализация / веса) | ✅ — [LICENSE_REVIEW.md](LICENSE_REVIEW.md) |
| Provider в TTS-очереди с fallback на Piper/Web Speech | ✅ `app/tts_engine.py::OmniVoiceProvider` |
| Изоляция тяжёлого PyTorch/Transformers runtime (lazy, в worker-thread) | ✅ |
| Fake-QA без model download (license gate + fallback не блокирует панель) | ✅ `tests/test_tts_core_transport.py` |
| Загрузка весов, установка, benchmark на реальном устройстве | ⏳ license gate снят владельцем; установка/benchmark — на устройстве владельца |

## Почему веса не качаем

Сам **код** OmniVoice — Apache-2.0: использовать и распространять можно. Но TTS-модель — это ещё
и **файлы весов** (~сотни МБ), выложенные отдельно на HuggingFace
([eustlb/higgs-audio-v2-tokenizer](https://huggingface.co/eustlb/higgs-audio-v2-tokenizer) —
промежуточный токенизатор; основные веса OmniVoice также выкладываются отдельными ревизиями).
У весов своя лицензия, и на model card сейчас стоит «License: More Information Needed» — то есть
**никто не подтвердил права на commercial use/redistribution**. Пока это не подтверждено,
установка = юридический риск для канала/проекта. Провайдер в коде жёстко заблокирован флагом
`weights_license_confirmed=False` и не начнёт работать, даже если пакет установить.

## Статус gate (обновлено 10.09)

Владелец подтвердил разрешение на использование весов (страница
[huggingface.co/k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)) — license gate снят,
`weights_license_confirmed=True`. Осталось: установка на целевом устройстве через `--ml`
(вручную), health-проверки под нагрузкой и benchmark RU/EN/UA — только на машине владельца,
не в панельной песочнице (нет GPU/аудио).

Дальше по этапам: [IMPLEMENTATION.md](IMPLEMENTATION.md).
