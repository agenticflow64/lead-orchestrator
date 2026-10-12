# Архитектура

## Основной вариант (n8n)

```mermaid
flowchart LR
    A[Клиент пишет<br/>Telegram-боту] --> B[n8n: Telegram Trigger<br/>webhook]
    B --> C[Python-функция<br/>классификация на GLM API]
    C --> D{Тип заявки?}
    D -- спам --> E[Тихо отклоняем<br/>в реестр со флагом]
    D -- всё остальное --> F[Google Sheets<br/>строка: имя, контакт, тип,<br/>срочность, суть, время]
    F --> G[Уведомление ответственному<br/>Telegram-сообщение]
    G -- срочность high --> H[Пометка СРОЧНО<br/>в тексте уведомления]
    C -. при ошибке API .-> I[Retry с backoff<br/>заявка не теряется]
```

Поток по шагам:

1. **Telegram Trigger** — n8n слушает обновления бота, входящее сообщение = заявка.
2. **Классификация** — Python-функция вызывает GLM API (OpenAI-совместимый, `GLM_BASE_URL`) с промптом-схемой:
   - `type`: `price_question` | `support` | `complaint` | `partnership` | `spam`
   - `urgency`: `low` | `medium` | `high`
   - извлечение полей: `name`, `contact`, `summary` (суть заявки в одном предложении)
3. **Запись** — строка в Google Sheets (демо: таблица-заглушка / локальный CSV-эндпоинт).
4. **Уведомление** — Telegram-сообщение ответственному (`TELEGRAM_CHAT_ID`); `high` urgency — с пометкой «СРОЧНО».
5. **Надёжность** — retry с backoff на вызов LLM; заявка не теряется при временном отказе API.

Почему n8n: заказчик видит workflow целиком, может менять правила (например, маршрут жалоб) без программиста. LLM-логика изолирована в Python-функции — её можно тестировать отдельно от оркестратора (скилл `lead-classifier-eval`).

## Вариант B — Kafka + микросервис (по запросу)

```mermaid
flowchart LR
    A[Telegram] --> B[Gateway-сервис<br/>FastAPI]
    B -->|produce| Q1[Kafka: leads.incoming]
    Q1 -->|consume| C[Classifier-сервис<br/>Python + GLM API]
    C -->|produce| Q2[Kafka: leads.classified]
    Q2 -->|consume| D[Sheets-writer]
    Q2 -->|consume| E[Notifier<br/>Telegram]
    C -->|ошибки классификации| DLQ[Kafka: leads.dlq]
```

Отличия от основного варианта:

- очередь `leads.incoming` / `leads.classified` развязывает приём, классификацию и доставку;
- consumer-группы позволяют масштабировать классификатор горизонтально;
- DLQ для заявок, которые не удалось классифицировать после ретраев;
- наблюдаемость: consumer lag, время пребывания заявки в очереди.

Когда вариант B оправдан: поток заявок выше возможностей одного n8n-инстанса, нужны гарантии доставки и аудит. Для демо-кейса избыточен — реализуем по запросу.
