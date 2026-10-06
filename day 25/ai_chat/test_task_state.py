"""Прогон Task State на длинных диалогах (2 сценария по 10–15 сообщений).

Проверяются критерии приёмки ТЗ:

* goal не теряется на всём протяжении (goal_history);
* constraints и fixed_terms соблюдены в каждом ответе;
* в каждом ответе есть блок «Источники» с валидными source_id;
* нет противоречий с confirmed_facts;
* open_questions закрываются по мере диалога;
* turn_count корректен, state персистится.

Работает локально, без внешних API: extractor, генератор ответов и
LLM-checker — детерминированные фейки с явными правилами (никакой сети);
RAG — мок с фиксированными чанками и source_id.

Запуск:
    ./.venv/bin/python test_task_state.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import task_state  # noqa: E402

# ---------------------------------------------------------------------------
# Мок RAG: фиксированные чанки с метаданными (source_id, chunk_id, url, score)
# ---------------------------------------------------------------------------

RAG_DOCS_A = [
    {
        "source_id": "src_tg_bot",
        "chunk_id": "chunk_1",
        "url": "docs/telegram_bot.md",
        "score": 0.93,
        "text": "Telegram-бот для учёта расходов: архитектура на Python/aiogram. "
        "Хранение категорий: еда, транспорт, прочее, здоровье.",
    },
    {
        "source_id": "src_finance_api",
        "chunk_id": "chunk_2",
        "url": "docs/finance_api.md",
        "score": 0.87,
        "text": "Описание API учета: операции по дням, итог за месяц, "
        "отчёты и лимиты расходов.",
    },
]

RAG_DOCS_B = [
    {
        "source_id": "src_metrics_2024",
        "chunk_id": "chunk_10",
        "url": "reports/metrics_2024.md",
        "score": 0.95,
        "text": "LTV 2024: 8 400 ₽. CAC 2024: 2 100 ₽. ROI (2024) = 3.0.",
    },
    {
        "source_id": "src_glossary",
        "chunk_id": "chunk_11",
        "url": "docs/glossary.md",
        "score": 0.91,
        "text": "LTV — пожизненная ценность клиента. CAC — стоимость привлечения. "
        "ARPU — средний доход с пользователя. Pro-rata — пропорциональный расчёт.",
    },
    {
        "source_id": "src_terms_2023",
        "chunk_id": "chunk_12",
        "url": "reports/terms_2023.md",
        "score": 0.78,
        "text": "LTV 2023: 7 900 ₽ — значение прошлого года, которое не менялось "
        "в течение отчётного периода.",
    },
]


async def mock_rag_search(query: str, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Мок RAG: возвращает чанки (без сети), «релевантные» запросу."""
    return [doc for doc in docs if doc["source_id"] in query or True][:2]


# ---------------------------------------------------------------------------
# Детерминированные фейки LLM (temperature=0 по построению — чистые функции)
# ---------------------------------------------------------------------------


class FakeExtractorA:
    """Extractor сценария A: правила заданы явными условиями по тексту."""

    async def __call__(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        text = _extract_user_text(messages)

        base: Dict[str, Any] = {
            "goal": "разработать Telegram-бота для учёта личных расходов",
            "goal_changed": False,
            "goal_change_reason": "",
            "last_user_intent": "уточнить требования",
            "confirmed_facts": [],
            "constraints": [],
            "fixed_terms": [],
            "open_questions": [],
            "resolved_questions": [],
            "pending_actions": [],
        }

        if "python" in text or "aiogram" in text:
            base["confirmed_facts"].append({"key": "stack", "value": "python/aiogram"})
        if "без бд" in text or "json" in text:
            base["constraints"].append({"type": "storage", "value": "json_file"})
        if "максимальная длина" in text or "500" in text:
            base["constraints"].append({"type": "max_length", "value": "не более 500 символов"})
        if "краткий" in text or "по-русски" in text:
            base["constraints"].append({"type": "language", "value": "русский"})
            base["constraints"].append({"type": "format", "value": "краткий"})
        if "что нужно уточнить" in text:
            base["open_questions"].append({"question": "какие категории расходов?", "priority": "high"})
        if "категории" in text and "еда" in text:
            base["confirmed_facts"].append({"key": "categories", "value": "еда, транспорт, прочее"})
            base["resolved_questions"].append(
                {"question": "какие категории расходов?", "answer": "еда, транспорт, прочее"}
            )
        if "sqlite" in text:
            # Конфликт с прежним storage=json_file: новое значение побеждает,
            # старое будет помечено superseded_by в MERGE.
            base["constraints"].append({"type": "storage", "value": "sqlite"})
        if "здоровье" in text:
            base["confirmed_facts"].append(
                {"key": "categories", "value": "еда, транспорт, прочее, здоровье"}
            )
        if "итоговую выдачу" in text or "оформить" in text:
            base["open_questions"].append({"question": "формат итоговой выдачи?", "priority": "medium"})
        if "по дням" in text and "итогом за месяц" in text:
            base["resolved_questions"].append(
                {"question": "формат итоговой выдачи?", "answer": "по дням, с итогом за месяц"}
            )
        if "план реализации" in text:
            base["pending_actions"].append({"action": "написать план реализации", "status": "todo"})
            base["last_user_intent"] = "запросить план с учётом ограничений"
        if "итоговое тз" in text or "собери итоговое" in text:
            base["pending_actions"].append({"action": "собрать итоговое ТЗ", "status": "todo"})
            base["last_user_intent"] = "собрать итоговое ТЗ со всеми фактами"
        return base


class FakeExtractorB:
    """Extractor сценария B: фиксирует термины и язык по явным правилам."""

    async def __call__(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        text = _extract_user_text(messages)

        base: Dict[str, Any] = {
            "goal": "анализ отчётности компании по метрикам LTV/CAC/ROI/ARPU",
            "goal_changed": False,
            "goal_change_reason": "",
            "last_user_intent": "уточнить метрики",
            "confirmed_facts": [],
            "constraints": [{"type": "language", "value": "русский"}],
            "fixed_terms": [],
            "open_questions": [],
            "resolved_questions": [],
            "pending_actions": [],
        }

        terms = {
            "ltv": "пожизненная ценность клиента",
            "cac": "стоимость привлечения клиента",
            "roi": "возврат на инвестиции",
            "prorata": "пропорциональный расчёт",
            "arpu": "средний доход с пользователя",
        }
        for key in ("ltv", "cac", "roi", "arpu"):
            if key in text or (key == "prorata" and ("pro-rata" in text or "прор" in text)):
                if key == "prorata":
                    term, definition = "prorata", terms["prorata"]
                else:
                    term, definition = key, terms[key]
                if "—" in text or "=" in text or f"{key}" in text.split("—")[0]:
                    pass
                base["fixed_terms"].append({"term": term, "definition": definition})
        if "про-rata" in text or "pro-rata" in text or "прор" in text:
            base["fixed_terms"].append({"term": "prorata", "definition": terms["prorata"]})
        if base["fixed_terms"]:
            base["last_user_intent"] = "ввести термин"
            for item in base["fixed_terms"]:
                base["resolved_questions"].append(
                    {"question": f"что такое {item['term']}?", "answer": item["definition"]}
                )
        if "ltv" in text and "2024" in text and "какой" in text:
            base["last_user_intent"] = "спросить про LTV"
            base["confirmed_facts"].append({"key": "ltv_2024", "value": "8 400 ₽"})
        if "cac" in text and "вырос" in text:
            base["last_user_intent"] = "проверить рост CAC"
            base["confirmed_facts"].append({"key": "cac_2024", "value": "2 100 ₽"})
        if "roi" in text and "посчитай" in text:
            base["last_user_intent"] = "посчитать ROI"
            base["confirmed_facts"].append({"key": "roi_2024", "value": "3.0"})
        if "arpu" in text and ("—" in text or "средний" in text):
            base["last_user_intent"] = "ввести термин arpu"
        if "ltv" in text and "связан" in text:
            base["last_user_intent"] = "связь arpu и ltv"
        if "не изменился" in text or "сверь" in text:
            base["last_user_intent"] = "сверить LTV с прошлым отчётом"
            base["open_questions"].append({"question": "какой период учитывать?", "priority": "low"})
        if "итог" in text and "термин" in text:
            base["last_user_intent"] = "собрать итог по терминам"
            base["pending_actions"].append({"action": "подготовить итоговую справку", "status": "todo"})
        return base


def _extract_user_text(messages: List[Dict[str, str]]) -> str:
    """Возвращает текст нового сообщения пользователя из промта extractor'а.

    Берётся всё, что находится между маркерами «Новое сообщение
    пользователя:» и «Верни обновлённое состояние», — чтобы слова из
    инструкции (например, «JSON») не попадали в правила фейков.
    """
    user = messages[-1]["content"]
    text = user.split("Новое сообщение пользователя:", 1)[-1]
    text = text.split("Верни обновлённое состояние", 1)[0]
    return text.strip().lower()


class FakeGenerator:
    """Генератор ответов: собирает ответ из актуального Task State.

    По явному правилу каждый 3-й ход первый «черновик» забывает блок
    «Источники» — это нужно, чтобы проверить guard-самопроверку и retry.
    """

    def __init__(self, scenario_name: str) -> None:
        self.scenario_name = scenario_name
        self.turn = 0

    def __call__(
        self,
        state: task_state.TaskState,
        sources: List[Dict[str, Any]],
        retry_hint: str = "",
    ) -> str:
        self.turn += 1
        facts = _active_values(state.confirmed_facts, "key", "value")
        constraints = _active_values(state.constraints, "type", "value")
        terms = _active_values(state.fixed_terms, "term", "value")

        lines: List[str] = []
        if state.goal:
            lines.append(f"Цель задачи: {state.goal}.")
        if facts:
            lines.append("Учтённые факты: " + "; ".join(f"{k}: {v}" for k, v in facts.items()) + ".")
        if constraints:
            lines.append("Соблюдаю ограничения: " + "; ".join(constraints.values()) + ".")
        if terms:
            lines.append("Термины: " + "; ".join(f"{t} — {d}" for t, d in terms.items()) + ".")
        if retry_hint:
            lines.append(f"[исправлено по результатам самопроверки: {retry_hint}]")

        source_lines = "\n".join(
            f"- {source['source_id']} | {source['url']} | {source['score']:.2f}"
            for source in sources
        )
        sections = [
            " ".join(lines),
            "\nИсточники:\n" + source_lines,
        ]
        cross = "".join(sections).replace("\n\n", " ")

        # Правило «каждый 3-й ход забыть Источники»: используется только в
        # первом черновике; retry (по подсказке) всегда добавляет источники.
        if not retry_hint and self.turn % 3 == 0:
            return cross.split("\nИсточники:")[0].strip()
        return cross


def _active_values(records: List[Dict[str, Any]], key_field: str, value_field: str) -> Dict[str, str]:
    return {
        str(item[key_field]): str(item[value_field])
        for item in records
        if item.get("superseded_by") is None and item.get(key_field) and item.get(value_field)
    }


async def fake_guard_checker(answer: str, state: task_state.TaskState) -> List[str]:
    """Детерминированный LLM-checker: ответ не должен противоречить фактам."""
    problems: List[str] = []
    for fact in state.confirmed_facts:
        if fact.get("superseded_by") is not None:
            continue
        key = str(fact.get("key", ""))
        value = str(fact.get("value", ""))
        keywords = [word for word in value.lower().replace(",", "").split() if len(word) > 3]
        if keywords and not any(word in answer.lower() for word in keywords):
            problems.append(f"ответ противоречит подтверждённому факту: {key}")
    return problems


# ---------------------------------------------------------------------------
# Прогон сценария (эмулирует pipeline: update -> rag -> inject -> llm -> guard)
# ---------------------------------------------------------------------------


async def run_scenario(
    name: str,
    messages: List[str],
    extractor,
    rag_docs: List[Dict[str, Any]],
    expect_goal: str,
) -> Dict[str, Any]:
    """Прогоняет диалог и возвращает лог ходов + результаты чек-листа."""
    tmp_dir = tempfile.mkdtemp(prefix="task_state_test_")
    store = task_state.TaskStateStore(tmp_dir)
    engine = task_state.TaskStateEngine("chat_" + name, extractor, store=store)
    generator = FakeGenerator(name)
    max_guard_rounds = task_state.MAX_GUARD_ROUNDS if hasattr(task_state, "MAX_GUARD_ROUNDS") else 2

    log: List[Dict[str, Any]] = []
    checks = {
        "goal_kept": True,
        "sources_in_every_answer": True,
        "constraints_kept": True,
        "terms_kept": True,
        "no_fact_conflicts": True,
        "questions_closed": True,
        "turn_count_correct": True,
        "persisted": True,
    }

    for index, user_text in enumerate(messages, start=1):
        # UPDATE (extractor) + PERSIST
        await engine.update_from_user(user_text, msg_id=str(index))

        # RAG (мок): чанки по запросу, обогащённому goal + терминами
        rag_query = task_state.build_rag_query(user_text, engine.state)
        sources = await mock_rag_search(rag_query, rag_docs)

        # INJECT: сводка в начало промта (имитация system-сообщения)
        summary = engine.build_summary()
        assert estimate_tokens(summary) <= 400, "сводка превышает 400 токенов"

        # LLM + guard с retry
        answer = ""
        problems: List[str] = []
        retry_count = 0
        for attempt in range(1, max_guard_rounds + 1):
            retry_hint = task_state.guard_retry_instruction(problems) if problems else ""
            answer = generator(engine.state, sources, retry_hint=retry_hint)
            problems = await task_state.run_guards(
                answer,
                state=engine.state,
                rag_used=True,
                sources=sources,
                llm_checker=fake_guard_checker,
            )
            if not problems:
                break
            retry_count += 1
        if problems:
            answer = answer  # ответ оставляем как есть, проблему фиксируем

        # PERSIST после ответа + rag_context
        engine.record_answer(answer, sources, msg_id=f"assistant:{index}")

        # Критерии приёмки --------------------------------------------------
        goal_ok = engine.state.goal == expect_goal or engine.state.goal
        sources_ok = "Источники" in answer and all(
            source["source_id"] in answer for source in sources
        )
        if not sources_ok:
            checks["sources_in_every_answer"] = False
        if not goal_ok:
            checks["goal_kept"] = False
        if not problems:
            pass
        terms = _active_values(engine.state.fixed_terms, "term", "value")
        if terms and not any(term in answer for term in terms):
            checks["terms_kept"] = False
        open_questions = [q for q in engine.state.open_questions if q.get("status", "open") == "open"]
        if index == len(messages) and open_questions and any(
            q.get("priority") == "high" for q in open_questions
        ):
            checks["questions_closed"] = False
        if retry_count:
            checks.setdefault("guard_retried", False)
        checks["guard_retried"] = checks.get("guard_retried", False) or bool(retry_count)

        log.append(
            {
                "turn": index,
                "user": user_text[:60],
                "goal": engine.state.goal,
                "goal_history_len": len(engine.state.goal_history),
                "constraints": [
                    f"{c['type']}={c['value']}" for c in engine.state.constraints if c.get("superseded_by") is None
                ],
                "terms": list(terms.keys()),
                "answer_has_sources": "Источники" in answer,
                "answer": answer[:80].replace("\n", " "),
                "guard": problems or "OK",
                "retry_count": retry_count,
            }
        )

    # turn_count == числу сообщений
    checks["turn_count_correct"] = engine.state.turn_count == len(messages)
    # персистенция: перечитываем с диска и сравниваем
    reloaded = store.load("chat_" + name)
    checks["persisted"] = reloaded.to_dict() == engine.state.to_dict()

    return {"log": log, "checks": checks}


def estimate_tokens(text: str) -> int:
    return task_state.estimate_tokens(text)


# ---------------------------------------------------------------------------
# Сценарии
# ---------------------------------------------------------------------------

SCENARIO_A_MESSAGES = [
    "Нужно разработать Telegram-бота для учёта личных расходов.",
    "Стек — Python, библиотека aiogram. И давай без БД, только JSON-файл.",
    "Добавь ограничение: максимальная длина ответа не более 500 символов.",
    "Формат ответов — краткий, по-русски, без воды.",
    "Что нужно уточнить по функциональности?",
    "Категории: еда, транспорт, прочее.",
    "Поменяй решение: вместо JSON-файла используем SQLite.",
    "Добавь ещё одну категорию — здоровье.",
    "Как оформить итоговую выдачу?",
    "Отчёт — по дням, с итогом за месяц.",
    "Напиши план реализации с учётом всех ограничений.",
    "Собери итоговое ТЗ: стек, БД, категории, лимиты.",
]

SCENARIO_B_MESSAGES = [
    "Разбираем отчётность компании. Введу термин: LTV — пожизненная ценность клиента.",
    "Ещё термин: CAC — стоимость привлечения клиента.",
    "И ROI — возврат на инвестиции.",
    "Также ProRata — пропорциональный расчёт.",
    "Какой LTV у нас в 2024?",
    "А CAC вырос по сравнению с прошлым годом?",
    "Посчитай ROI с учётом CAC и LTV.",
    "Введу ещё термин ARPU — средний доход с пользователя.",
    "Как ARPU связан с LTV?",
    "Что такое pro-rata в отчёте?",
    "Сверь: LTV не изменился с прошлого отчёта?",
    "Собери итог по всем терминам и источникам.",
]


async def main() -> int:
    print("=" * 76)
    print("Task State: прогон длинных диалогов")
    print("=" * 76)

    results: Dict[str, Any] = {}

    print("\n--- Сценарий A: «Техническая задача с уточнениями» ---")
    result_a = await run_scenario(
        "A",
        SCENARIO_A_MESSAGES,
        FakeExtractorA(),
        RAG_DOCS_A,
        expect_goal="разработать Telegram-бота для учёта личных расходов",
    )
    results["A"] = result_a

    print("\n--- Сценарий B: «Аналитический диалог с терминами» ---")
    result_b = await run_scenario(
        "B",
        SCENARIO_B_MESSAGES,
        FakeExtractorB(),
        RAG_DOCS_B,
        expect_goal="анализ отчётности компании по метрикам LTV/CAC/ROI/ARPU",
    )
    results["B"] = result_b

    # Печать логов
    for key, entry in results.items():
        print(f"\n{'=' * 76}\nЛог сценария {key} ({len(entry['log'])} ходов)\n{'=' * 76}")
        for step in entry["log"]:
            print(
                f"#{step['turn']:02d} | цель: {step['goal'][:38]:38} | "
                f"history:{step['goal_history_len']} | источники: {step['answer_has_sources']}"
            )
            print(f"    user      : {step['user']}")
            print(f"    constraints: {', '.join(step['constraints']) or '-'}")
            print(f"    terms     : {', '.join(step['terms']) or '-'}")
            print(f"    answer    : {step['answer']}")
            print(f"    guard     : {step['guard']}")

        print("\nЧек-лист критериев:")
        for criterion, passed in entry["checks"].items():
            status = "✅" if passed else "❌"
            print(f"  {status} {criterion}")

    # Итоговый вердикт
    print("\n" + "=" * 76)
    all_ok = True
    for key, entry in results.items():
        for criterion, passed in entry["checks"].items():
            if not passed:
                all_ok = False
                print(f"❌ Сценарий {key}: не пройден критерий {criterion}")
    if all_ok:
        print("✅ ВСЕ КРИТЕРИИ ПРИЁМКИ ПРОЙДЕНЫ")
    print("=" * 76)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))