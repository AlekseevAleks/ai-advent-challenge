import os

from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request
from openai import OpenAI

app = Flask(__name__)

KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")
MODEL = "gpt-5.4-mini"
TEMPERATURES = [0, 0.7, 1.2]


def read_api_key():
    """Читает API-ключ и URL из файла api_key.txt (ключ на первой строке, URL на второй)"""
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        key = lines[0] if lines else None
        base_url = lines[1] if len(lines) > 1 else None
        return key, base_url
    except OSError:
        return None, None


def get_client():
    key, base_url = read_api_key()
    if not key:
        return None
    return OpenAI(api_key=key, base_url=base_url)


@app.route("/")
def index():
    return render_template("index.html")


def ask_ai(message, temperature):
    client = get_client()
    response = client.responses.create(
        model=MODEL,
        input=message,
        temperature=temperature,
        store=True,
    )
    return response.output_text


def build_comparison_prompt(message, responses):
    parts = [f"Вопрос: {message}", ""]
    for t in TEMPERATURES:
        parts.append(f"--- Ответ (temperature = {t}) ---")
        parts.append(responses[t])
        parts.append("")
    parts.append(
        "Сравни эти три ответа по критериям: точность, креативность, разнообразие. "
        "Для каждого критерия укажи, какая настройка temperature справилась лучше и почему. "
        "В конце дай рекомендацию: для каких задач лучше подходит каждая настройка temperature."
    )
    return "\n".join(parts)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Сообщение не может быть пустым"}), 400

    client = get_client()
    if client is None:
        return jsonify({"error": "API-ключ не найден в файле api_key.txt"}), 500

    try:
        with ThreadPoolExecutor(max_workers=len(TEMPERATURES)) as pool:
            futures = {pool.submit(ask_ai, message, t): t for t in TEMPERATURES}
            responses = {}
            for future, t in futures.items():
                responses[t] = future.result()

        comparison = ask_ai(build_comparison_prompt(message, responses), 0)

        return jsonify({
            "responses": [
                {"temperature": t, "text": responses[t]}
                for t in TEMPERATURES
            ],
            "comparison": comparison,
        })
    except Exception as e:
        error_msg = str(e)
        if "insufficient_quota" in error_msg.lower():
            return jsonify({"error": "Недостаточно средств на аккаунте OpenAI"}), 402
        if "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            return jsonify({"error": "Недействительный API-ключ"}), 401
        if "rate_limit" in error_msg.lower():
            return jsonify({"error": "Превышен лимит запросов. Подождите немного."}), 429
        return jsonify({"error": f"Ошибка: {error_msg}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Сервис запущен: http://localhost:{port}")
    app.run(debug=True, host="0.0.0.0", port=port)