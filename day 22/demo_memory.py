"""Демонстрация трёхслойной памяти агента с логами и ablation-экспериментом.

Скрипт прогоняет диалог из 4 реплик, показывает, что попало в каждый слой
после каждого шага, а затем повторяет ключевой вопрос при отключённых слоях
(ablation), чтобы показать, как меняется контекст и ответ агента.

Запуск::

    python demo_memory.py

Скрипт не обращается к внешнему API: ответы агента имитируются на основе
собранного контекста, чтобы демонстрация была воспроизводимой и без ключа.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List

import memory_layers
from memory_layers import LAYER_LONG, LAYER_SHORT, LAYER_WORKING, MemoryManager

SESSION_ID = "demo-session"
USER_ID = "demo-user"

# Сценарий: 4 реплики, покрывающие все три слоя.
DIALOG: List[str] = [
    "Привет! Меня зовут Алексей, я предпочитаю краткие ответы без воды.",
    "Поставь задачу: нужно сделать отчёт по продажам за квартал, дедлайн — пятница.",
    "Промежуточный результат: данные за январь и февраль уже собраны.",
    "Спасибо, всё готово!",
]

# Вопрос, на котором проверяем влияние слоёв.
PROBE_QUESTION = "Как меня зовут и что за задача у нас была?"


def _print_header(title: str) -> None:
    """Печатает заголовок раздела."""
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _print_layers(manager: MemoryManager, session_id: str, user_id: str) -> None:
    """Печатает содержимое всех трёх слоёв памяти."""
    snapshot = manager.snapshot(session_id, user_id)

    print("\n  SHORT-TERM (последние сообщения диалога):")
    if snapshot["short_term"]:
        for item in snapshot["short_term"]:
            preview = item["content"][:70]
            print(f"    - [{item['role']}] {preview}")
    else:
        print("    (пусто)")

    print("\n  WORKING (состояние задачи):")
    working = snapshot["working"]
    has_working = any(
        working.get(key) for key in ("goal", "constraints", "results", "todo")
    )
    if has_working:
        for key in ("goal", "constraints", "todo", "results", "status"):
            value = working.get(key)
            if value:
                print(f"    - {key}: {value}")
    else:
        print("    (пусто)")

    print("\n  LONG-TERM (устойчивые факты о пользователе):")
    if snapshot["long_term"]:
        for fact in snapshot["long_term"]:
            print(
                f"    - {fact['fact']} "
                f"[{fact['category']}, подтверждений: {fact['confirmations']}]"
            )
    else:
        print("    (пусто)")


def _fake_agent_reply(context: List[Dict[str, str]]) -> str:
    """Имитирует ответ агента на основе собранного контекста.

    Показывает, какие слои реально дошли до модели: если в контексте есть
    факт из long-term или цель из working, агент их «вспоминает».
    """
    system_text = "\n".join(
        message["content"] for message in context if message["role"] == "system"
    )
    dialogue_text = "\n".join(
        message["content"] for message in context if message["role"] != "system"
    )
    knows_name = "Алексей" in system_text
    knows_style = "краткие ответы" in system_text.lower()
    # Цель задачи видна либо из working (system), либо из истории диалога.
    knows_task = "отчёт по продажам" in system_text.lower()
    task_from_dialogue = "отчёт по продажам" in dialogue_text.lower()

    parts: List[str] = []
    if knows_name:
        parts.append("Вас зовут Алексей.")
    else:
        parts.append("Имени я не помню.")
    if knows_task:
        parts.append("Задача — отчёт по продажам за квартал (из рабочей памяти).")
    elif task_from_dialogue:
        parts.append("Задача — отчёт по продажам (только из истории диалога).")
    else:
        parts.append("Про задачу с отчётом мне ничего не известно.")
    if knows_style:
        parts.append("Отвечаю кратко, как вы предпочитаете.")
    return " ".join(parts)
def run_dialog(manager: MemoryManager) -> None:
    """Прогоняет сценарий диалога, логируя состояние слоёв после каждого шага."""
    _print_header("ШАГ 1. ДИАЛОГ И ЗАПИСЬ В СЛОИ ПАМЯТИ")

    for index, message in enumerate(DIALOG, start=1):
        print(f"\n--- Реплика {index}: {message}")

        decision = manager.route_and_store(SESSION_ID, USER_ID, message)
        manager.add_short_term(SESSION_ID, {"role": "user", "content": message})
        manager.log_step(f"user:{index}", decision)

        print(f"  Роутер -> слой '{decision.layer}'")
        print(f"  Обоснование: {decision.reason}")

        if memory_layers.is_task_completed(message):
            collapsed = manager.collapse_working(SESSION_ID, USER_ID)
            if collapsed:
                print(f"  Задача завершена -> схлопнута в long-term: {collapsed['fact']}")

        # Имитируем ответ агента и тоже пишем его в short-term.
        context = manager.build_prompt_messages(SESSION_ID, USER_ID, message)
        reply = _fake_agent_reply(context)
        manager.add_short_term(SESSION_ID, {"role": "assistant", "content": reply})
        print(f"  Ответ агента: {reply}")

        _print_layers(manager, SESSION_ID, USER_ID)


def run_ablation() -> None:
    """Эксперимент «что если»: отключаем слои и смотрим на контекст и ответ."""
    _print_header("ШАГ 2. ABLATION-ЭКСПЕРИМЕНТ")

    scenarios = [
        ("Все слои включены", [LAYER_SHORT, LAYER_WORKING, LAYER_LONG]),
        ("Без long-term", [LAYER_SHORT, LAYER_WORKING]),
        ("Без working", [LAYER_SHORT, LAYER_LONG]),
        ("Без short-term", [LAYER_WORKING, LAYER_LONG]),
        ("Только short-term", [LAYER_SHORT]),
    ]

    for title, layers in scenarios:
        # Для каждого сценария — своя БД, чтобы long-term был одинаковым.
        db_path = os.path.join(tempfile.gettempdir(), f"demo_memory_{'_'.join(layers)}.db")
        if os.path.exists(db_path):
            os.remove(db_path)

        manager = MemoryManager(
            long_term=memory_layers.LongTermMemory(db_path),
            enabled_layers=layers,
        )
        # Наполняем слои тем же сценарием.
        for message in DIALOG:
            manager.route_and_store(SESSION_ID, USER_ID, message)
            manager.add_short_term(SESSION_ID, {"role": "user", "content": message})
            if memory_layers.is_task_completed(message):
                manager.collapse_working(SESSION_ID, USER_ID)

        context = manager.build_prompt_messages(SESSION_ID, USER_ID, PROBE_QUESTION)
        reply = _fake_agent_reply(context)

        print(f"\n--- {title} (слои: {', '.join(layers)})")
        print(f"  Сообщений в контексте: {len(context)}")
        for message in context:
            if message["role"] == "system":
                preview = message["content"].replace("\n", " | ")[:110]
                print(f"    [system] {preview}")
        print(f"  Ответ агента: {reply}")

        os.remove(db_path)


def main() -> None:
    """Точка входа демо-скрипта."""
    db_path = os.path.join(tempfile.gettempdir(), "demo_memory_main.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    manager = MemoryManager(long_term=memory_layers.LongTermMemory(db_path))

    run_dialog(manager)

    _print_header("ШАГ 3. ИТОГОВЫЙ СНИМОК СЛОЁВ")
    print(json.dumps(manager.snapshot(SESSION_ID, USER_ID), ensure_ascii=False, indent=2))

    run_ablation()

    _print_header("ВЫВОД")
    print(
        "short-term  — реплики диалога (FIFO, лимит 20 сообщений / ~2000 токенов);\n"
        "working     — цель, ограничения, план и промежуточные результаты задачи;\n"
        "long-term   — устойчивые факты (имя, предпочтения, итог задачи) в SQLite.\n\n"
        "Ablation показывает: без long-term агент не помнит имя и предпочтения,\n"
        "без working — теряет цель задачи, без short-term — не видит ход диалога."
    )

    os.remove(db_path)


if __name__ == "__main__":
    main()
