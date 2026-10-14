# License review — OmniVoice PoC (10.09.2026)

Проверено через официальные страницы репозиториев и HuggingFace. Выводы — без переговоров
с авторами; ссылки приведены для повторной проверки.

| Компонент | Где | Лицензия | Commercial / redistribution |
|---|---|---|---|
| Код k2-fsa/OmniVoice | github.com/k2-fsa/omnivoice (LICENSE) | Apache-2.0 | ✅ разрешено; сохраняем attribution/NOTICE |
| Higgs Audio v2 tokenizer — transformers-реализация | github.com/huggingface/transformers `models/higgs_audio_v2_tokenizer` | Apache-2.0 (Boson AI + HuggingFace) | ✅ разрешено |
| **Веса** eustlb/higgs-audio-v2-tokenizer | huggingface.co/eustlb/higgs-audio-v2-tokenizer | **Не подтверждена** — model card: «License: More Information Needed» | ⛔ не подтверждено |
| Основные веса OmniVoice (checkpoint ревизии) | release/model card репозитория | **Не подтверждена** на момент ревизии | ⛔ не подтверждено |

## Решение владельца (10.09.2026)

Владелец подтвердил («я нашёл — всё разрешено»): официальная страница весов
[huggingface.co/k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) (у авторов проекта)
разрешает использование. License gate снят: `weights_license_confirmed=True` в
`app/tts_engine.py`. Примечание: при первом production-запуске сверить license-тег на странице
весов и записи здесь; смена ревизии весов = повторная проверка.

## Вывод

- Код использовать можно уже сейчас (адаптер в `app/tts_engine.py`).
- Веса: разрешение подтверждено владельцем 10.09.2026 (см. выше). Установка — только вручную
  на целевом устройстве через `--ml`; в панельной песочнице веса не скачиваются.

## Путь снятия блокера

1. Проверить releases/model cards обеих весовых ревизий на предмет явной лицензии
   (допустимо: Apache-2.0, MIT, или иная с явным commercial use).
2. Если не найдена — issue/письмо авторам OmniVoice и Boson AI с вопросом о лицензии весов;
   ответ зафиксировать здесь с датой и ссылкой.
3. Решение владельца → обновить этот файл и PLAN_TODO → установка через `--ml`.

Повторная ревизия требуется также при смене версии/ревизии весов: новая ревизия = новая проверка.
