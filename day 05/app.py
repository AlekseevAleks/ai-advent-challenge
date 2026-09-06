import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")

# Ссылки на сайты провайдеров по slug из данных моделей
PROVIDER_LINKS = {
    "openai": "https://openai.com",
    "anthropic": "https://anthropic.com",
    "google": "https://deepmind.google",
    "meta": "https://ai.meta.com",
    "mistralai": "https://mistral.ai",
    "deepseek": "https://deepseek.com",
    "qwen": "https://qwen.ai",
    "x-ai": "https://x.ai",
    "z-ai": "https://z.ai",
    "moonshotai": "https://kimi.com",
    "nvidia": "https://nvidia.com",
    "sber": "https://developers.sber.ru/gigachat",
    "yandex": "https://yandex.ru",
    "tencent": "https://hunyuan.tencent.com",
    "minimax": "https://minimax.io",
    "cohere": "https://cohere.com",
    "amazon": "https://aws.amazon.com/ai/",
    "baidu": "https://yiyan.baidu.com",
    "bytedance-seed": "https://seed.bytedance.com",
    "perplexity": "https://perplexity.ai",
    "stepfun": "https://stepfun.com",
    "xiaomi": "https://xiaomi.com",
    "sakana": "https://sakana.ai",
    "poolside": "https://poolside.ai",
    "aion-labs": "https://aionlabs.ai",
    "kwaipilot": "https://kwaipilot.com",
    "thinkingmachines": "https://thinkingmachines.ai",
    "inception": "https://inceptionlabs.ai",
    "writer": "https://writer.com",
    "upstage": "https://upstage.ai",
    "nousresearch": "https://nousresearch.com",
    "morph": "https://morph.ai",
    "rekaai": "https://reka.ai",
    "arcee-ai": "https://arcee.ai",
    "perceptron": "https://perceptron.ai",
    "aiesa": "https://aiesa.ai",
    "relace": "https://relace.ai",
    "sentence-transformers": "https://sbert.net",
    "intfloat": "https://huggingface.co/intfloat",
    "baai": "https://bge.aicup.dev",
    "ibm-granite": "https://www.ibm.com/granite",
    "microsoft": "https://microsoft.com/ai",
    "meta-llama": "https://ai.meta.com/llama",
    "gryphe": "https://huggingface.co/gryphe",
    "mancer": "https://mancer.tech",
    "sao10k": "https://huggingface.co/Sao10K",
    "undi95": "https://huggingface.co/undi95",
    "thedrummer": "https://huggingface.co/TheDrummer",
    "anthracite-org": "https://huggingface.co/anthracite-org",
    "bytedance": "https://bytedance.com",
    "google": "https://deepmind.google",
}


def read_api_key():
    """Читает API-ключ и URL из файла api_key.txt (ключ на первой строке, URL на второй)"""
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip().rstrip("%") for line in f if line.strip()]
        key = lines[0] if lines else None
        base_url = lines[1] if len(lines) > 1 else None
        return key, base_url
    except OSError:
        return None, None


def get_credentials():
    key, base_url = read_api_key()
    if not key:
        return None, None
    return key, base_url


def provider_link(model_id):
    """Возвращает ссылку на сайт провайдера по id модели"""
    slug = model_id.split("/")[0].lower()
    return PROVIDER_LINKS.get(slug)


def fetch_models():
    """Загружает список моделей с типом chat из API polza"""
    key, base_url = get_credentials()
    if not key or not base_url:
        return []
    try:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    models = []
    for m in data.get("data", []):
        if m.get("type") != "chat":
            continue
        provider = m.get("top_provider", {}) or {}
        pricing = provider.get("pricing", {}) or {}
        models.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "context_length": provider.get("context_length"),
            "max_tokens": provider.get("max_completion_tokens"),
            "prompt_per_million": pricing.get("prompt_per_million"),
            "completion_per_million": pricing.get("completion_per_million"),
            "link": provider_link(m["id"]),
        })
    return models


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/models")
def models():
    models = fetch_models()
    if not models:
        return jsonify({"error": "Не удалось загрузить список моделей"}), 502
    return jsonify({"models": models})


def ask_model(message, model_id):
    """Отправляет запрос к выбранной модели, возвращает текст, время, токены и стоимость"""
    key, base_url = get_credentials()
    start = time.monotonic()
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": message}],
            "temperature": 0.7,
            "max_tokens": 2000,
        },
        timeout=300,
    )
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    data = resp.json()

    text = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage", {}) or {}
    return {
        "model": model_id,
        "text": text,
        "time_sec": round(elapsed, 2),
        "tokens": usage.get("total_tokens") or 0,
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "cost_rub": round(float(usage.get("cost_rub") or 0), 6),
    }


def build_comparison_prompt(message, results):
    parts = [f"Вопрос: {message}", ""]
    for r in results:
        parts.append(f"--- Модель: {r['model']} ---")
        parts.append(f"Время ответа: {r['time_sec']} сек, токенов: {r['tokens']}, стоимость: {r['cost_rub']} руб")
        parts.append(r["text"])
        parts.append("")
    parts.append(
        "Сравни эти три ответа по критериям: качество, скорость, ресурсоёмкость (стоимость и токены). "
        "Для каждого критерия укажи, какая модель справилась лучше и почему. "
        "В конце дай короткий вывод о различиях между моделями."
    )
    return "\n".join(parts)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    models = data.get("models") or []

    if not message:
        return jsonify({"error": "Сообщение не может быть пустым"}), 400
    if len(models) != 3:
        return jsonify({"error": "Нужно выбрать ровно три модели"}), 400

    key, base_url = get_credentials()
    if not key:
        return jsonify({"error": "API-ключ не найден в файле api_key.txt"}), 500

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(ask_model, message, m): m for m in models}
            results = []
            for future, m in futures.items():
                try:
                    results.append(future.result())
                except Exception as e:
                    return jsonify({"error": f"Модель {m}: {e}"}), 500

        results.sort(key=lambda r: models.index(r["model"]))
        comparison = ask_model(build_comparison_prompt(message, results), models[0])

        return jsonify({
            "responses": results,
            "comparison": comparison["text"],
        })
    except Exception as e:
        error_msg = str(e)
        if "insufficient_quota" in error_msg.lower():
            return jsonify({"error": "Недостаточно средств на аккаунте"}), 402
        if "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            return jsonify({"error": "Недействительный API-ключ"}), 401
        if "rate_limit" in error_msg.lower():
            return jsonify({"error": "Превышен лимит запросов. Подождите немного."}), 429
        return jsonify({"error": f"Ошибка: {error_msg}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Сервис запущен: http://localhost:{port}")
    app.run(debug=True, host="0.0.0.0", port=port)