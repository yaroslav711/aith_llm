# AI Mediator for couples

**Прототип агента, который ведет два параллельных чата с партнерами и помогает найти решение конфликта.**

Ссылка на репозиторий: https://github.com/yaroslav711/aith_llm

Выполнили: 
- Москаленко Ярослав Александрович [tg: @yaroslav2207]
- Моисеенков Владислав Юрьевич [tg: @vlad1545]

## Почему нет RAG и собранных данных?
- Если честно, мы не до конца поняли, почему RAG идет первым этапом: изначально мы перед собой поставили цель - "создать хорошую систему", но на старте было не ясно, какие именно методы для этого потребуются, поэтому мы начали с Proof of Concept в виде промпта
- Текущая реализация через промпт показала то, что LLM хорошо ориентируется в двух чатах параллельно и не теряется
- Мы провели Demo со специалистом парной психологии, получили от него инсайты и понимание, что уже работает хорошо, а что требует доработки
- Сделали вывод: RAG нам все-таки нужен, будем готовить каркас и собирать данные к следующему чекпоинту

## Как это работает сейчас
- У каждого партнера свой чат (`user_1` и `user_2`), LLM общается с каждым отдельно
- LLM интересуетcя, что важно каждому из них, ищет общую цель и помогает к ней придти
- Помогает выстраить доверительное, а не обвинительное общение (сглаживает углы и заставляет понять и себя и партнера)
- В процессе общения, делится точкой зрения партнера
- Находит точки соприкосновения и помогает найти компромис / решение проблемы

## Архитектура: Multi-Agent System

### Агент 1: Onboarding (7-10 сообщений)
- **Задача**: Установить контакт, использовать хуки для вовлечения
- **Классификацировать конфликт**:
  - Разрешимость (Готтман): resolvable / perpetual / gridlocked
  - Сфера: деньги, секс, дети, родственники, быт, время, планы
  - Природа: рациональный / эмоциональный
  - Форма: открытый / скрытый
  - Уровень угрозы: базовый (доверие) / поверхностный
- **Передача**: После классификации → бесшовный переход к Therapy Agent

### Агент 2: Therapy (глубокая работа)
- **Задача**: Вести пару к решению, используя психологические школы
- **Подход**: На основе классификации подключается специализированный плейбук
- **Школы**: EFT, CBT, Gottman, ТА, Psychodynamic, Systemic, Existential
- **Инструменты**: Инсайты, рефрейминг, микрошаги, синтез
- **Границы**: Если клиника/травма → направляет к специалисту

## Быстрый старт
```bash
cd /Users/y.moskalenko/Desktop/llm_project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Создайте `.env` в корне проекта:
```
OPENAI_API_KEY=sk-...
DEFAULT_MODEL=gpt-4.1
PORT=8000
```

Запуск:
```bash
python app.py
```

Открыть UI: http://localhost:8000

## Метрики качества

### Выбранные метрики
- **No double-messaging**: агент не отправляет пользователю новое сообщение, пока тот не ответил на предыдущее.
- **Recipient correctness**: каждое сообщение от агента имеет `recipient` ∈ `{user_1, user_2}`.
- **Turn-to-handoff**: номер хода, на котором агент впервые переключился в `therapy`.
- **Schema validity rate**: доля ходов, где ответ валиден по `AgentResponse`.

### Итоговые значения метрик (пример прогона)
Агрегат по файлу `eval/out/summary_20251213_151338.json` (24 прогона, 8 сценариев):
- **Schema validity rate**: **1.00**
- **Recipient correctness**: **1.00**
- **Turn-to-handoff**: mean **7.17**, median **7.50**, min **6**, max **8** (handoff rate **1.00**)
- **No double-messaging violations**: total **15**, mean/run **0.63**, median/run **0**, max/run **3**
- **Latency**:
  - p50: mean **7264 ms**, median **6763 ms** (min **2532 ms**, max **11777 ms**)
  - p95: mean **19650 ms**, median **19872 ms** (min **13466 ms**, max **29158 ms**)

## Структура
```
llm_project/
├── app.py                      # FastAPI endpoints (тонкий слой)
├── src/
│   ├── agents/
│   │   ├── onboarding.py       # Onboarding agent
│   │   ├── therapy.py          # Therapy agent  
│   │   └── graph.py            # LangGraph workflow
│   ├── classification/
│   │   └── classifier.py       # Multi-axis classifier
│   ├── playbooks/
│   │   └── loader.py           # Playbook selection
│   └── models/
│       └── schemas.py          # Pydantic models
├── prompts/
│   ├── onboarding.md           # Onboarding prompt
│   ├── therapy.md              # Therapy prompt
│   ├── conflict_mapping.md     # Mapping logic
│   └── playbooks/              # 7 psychological approaches
├── static/
│   └── index.html              # Web UI
├── eval/
│   ├── scenarios.json          # Набор сценариев диалогов для offline-eval
│   ├── run_eval.py             # Прогон сценариев + расчёт метрик + запись артефактов
│   └── out/                    # Результаты прогонов (summary_*.json, transcript_*.jsonl)
└── requirements.txt            # Includes langgraph, langchain
```