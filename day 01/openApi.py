import os
import json
from openai import OpenAI

# Файл для хранения ключа
KEY_FILE = "api_key.txt"

def get_api_key():
    """Получить ключ из файла или запросить у пользователя"""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'r') as f:
            key = f.read().strip()
            if key:
                return key
    
    # Если файл пустой или не существует
    key = input("Введите ваш API ключ: ").strip()
    with open(KEY_FILE, 'w') as f:
        f.write(key)
    return key

# Инициализация клиента
client = OpenAI(
    api_key=get_api_key()
)

# Ввод запроса от пользователя
prompt = input("Ваш вопрос: ")

# Отправка запроса
response = client.responses.create(
  model="gpt-5.4-mini",
  input=prompt,
  store=True,
)

# Вывод ответа
print("\nОтвет:", response.output_text);
