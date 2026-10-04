/** Интернационализация.

Архитектура готова к добавлению английского языка: t(key, fallback) ищет
перевод в словаре `translations`; если его нет — возвращает fallback (русский
текст). Для добавления языка достаточно создать словарь и зарегистрировать его.
*/

type Dict = Record<string, string>;

const translations: Dict = {
  // Зарезервированные ключи (сейчас языки = русский, fallback используется напрямую)
};

export function t(key: string, fallback: string): string {
  const value = translations[key];
  return value !== undefined ? value : fallback;
}

export const LANG = "ru";