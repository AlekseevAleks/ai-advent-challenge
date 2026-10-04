/** Страница «Настройки»: конфигурация backend, статус Ollama, интерфейс и хранилище. */

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Copy,
  Cpu,
  HardDrive,
  Moon,
  RefreshCw,
  Server,
  Settings,
  Sun,
  TriangleAlert,
} from "lucide-react";
import { t } from "../app/i18n";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Input,
  Kbd,
  Spinner,
  ToggleSwitch,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { getOllamaStatus, getSettings, patchSettings, testOllama } from "../services/api";
import type { AppSettings, OllamaStatus, OllamaTest, SettingsPatch } from "../types/api";
import { formatBytes } from "../lib/utils";
import { useTheme } from "../hooks/useTheme";

/** Поля формы backend-конфигурации (значения из settings.backend). */
interface BackendForm {
  ollama_url: string;
  embedding_model: string;
  embedding_batch_size: number;
  embedding_retries: number;
  ollama_timeout: number;
  ollama_connection_timeout: number;
  max_file_size_mb: number;
  max_files_per_request: number;
  default_chunk_size: number;
  default_chunk_overlap: number;
  default_structural_max_chunk_size: number;
  default_structural_min_chunk_size: number;
}

type TextField = "ollama_url" | "embedding_model";
type NumericField = Exclude<keyof BackendForm, TextField>;

function fromBackend(b: AppSettings["backend"]): BackendForm {
  return {
    ollama_url: b.ollama_url,
    embedding_model: b.embedding_model,
    embedding_batch_size: b.embedding_batch_size,
    embedding_retries: b.embedding_retries,
    ollama_timeout: b.ollama_timeout,
    ollama_connection_timeout: b.ollama_connection_timeout,
    max_file_size_mb: b.max_file_size_mb,
    max_files_per_request: b.max_files_per_request,
    default_chunk_size: b.default_chunk_size,
    default_chunk_overlap: b.default_chunk_overlap,
    default_structural_max_chunk_size: b.default_structural_max_chunk_size,
    default_structural_min_chunk_size: b.default_structural_min_chunk_size,
  };
}

export function SettingsPage() {
  const toast = useToast();
  const { dark, toggle } = useTheme();

  // загрузка настроек
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [form, setForm] = useState<BackendForm | null>(null);
  const [saving, setSaving] = useState(false);

  // Ollama
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null);
  const [ollamaStatusLoading, setOllamaStatusLoading] = useState(false);
  const [ollamaStatusError, setOllamaStatusError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<OllamaTest | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getSettings();
      setSettings(s);
      setForm(fromBackend(s.backend));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshStatus = useCallback(async () => {
    setOllamaStatusLoading(true);
    setOllamaStatusError(null);
    try {
      setOllamaStatus(await getOllamaStatus());
    } catch (e) {
      setOllamaStatus(null);
      setOllamaStatusError(e instanceof Error ? e.message : String(e));
    } finally {
      setOllamaStatusLoading(false);
    }
  }, []);

  const handleTest = useCallback(async () => {
    setTesting(true);
    try {
      setTestResult(await testOllama());
    } catch (e) {
      setTestResult(null);
      toast.error(
        t("settings.ollamaTestError", "Ошибка проверки Ollama"),
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setTesting(false);
    }
  }, [toast]);

  const setTextField = (key: TextField, value: string) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const setNumberField = (key: NumericField, value: number) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const handleSave = useCallback(async () => {
    if (!settings || !form) return;
    setSaving(true);
    // отправляем только изменённые поля
    const patch: SettingsPatch = {};
    if (form.ollama_url !== settings.backend.ollama_url) patch.ollama_url = form.ollama_url;
    if (form.embedding_model !== settings.backend.embedding_model) patch.embedding_model = form.embedding_model;
    if (form.embedding_batch_size !== settings.backend.embedding_batch_size) patch.embedding_batch_size = form.embedding_batch_size;
    if (form.embedding_retries !== settings.backend.embedding_retries) patch.embedding_retries = form.embedding_retries;
    if (form.ollama_timeout !== settings.backend.ollama_timeout) patch.ollama_timeout = form.ollama_timeout;
    if (form.ollama_connection_timeout !== settings.backend.ollama_connection_timeout) patch.ollama_connection_timeout = form.ollama_connection_timeout;
    if (form.max_file_size_mb !== settings.backend.max_file_size_mb) patch.max_file_size_mb = form.max_file_size_mb;
    if (form.max_files_per_request !== settings.backend.max_files_per_request) patch.max_files_per_request = form.max_files_per_request;
    if (form.default_chunk_size !== settings.backend.default_chunk_size) patch.default_chunk_size = form.default_chunk_size;
    if (form.default_chunk_overlap !== settings.backend.default_chunk_overlap) patch.default_chunk_overlap = form.default_chunk_overlap;
    if (form.default_structural_max_chunk_size !== settings.backend.default_structural_max_chunk_size) patch.default_structural_max_chunk_size = form.default_structural_max_chunk_size;
    if (form.default_structural_min_chunk_size !== settings.backend.default_structural_min_chunk_size) patch.default_structural_min_chunk_size = form.default_structural_min_chunk_size;
    try {
      const updated = await patchSettings(patch);
      setSettings(updated);
      setForm(fromBackend(updated.backend));
      toast.success(t("settings.saved", "Настройки сохранены"));
    } catch (e) {
      toast.error(
        t("settings.saveError", "Ошибка сохранения настроек"),
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setSaving(false);
    }
  }, [settings, form, toast]);

  const handleReset = useCallback(() => {
    if (!settings) return;
    setForm(fromBackend(settings.backend));
  }, [settings]);

  async function copyPullCommand(cmd: string) {
    try {
      await navigator.clipboard.writeText(cmd);
    } catch {
      // fallback: скрытый textarea
      const ta = document.createElement("textarea");
      ta.value = cmd;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24">
        <Spinner label={t("settings.loading", "Загрузка настроек…")} />
      </div>
    );
  }

  const modelChanged =
    !!settings && !!form && form.embedding_model !== settings.backend.embedding_model;

  if (!settings || !form) {
    return (
      <div className="space-y-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Settings className="h-6 w-6 text-primary DEFAULT" />
          {t("settings.title", "Настройки")}
        </h1>
        <Alert variant="error" icon={<TriangleAlert className="h-4 w-4" />}>
          <span>{t("settings.loadError", "Не удалось загрузить настройки")}</span>
          {error ? <p className="mt-1 text-xs opacity-80">{error}</p> : null}
        </Alert>
        <Button variant="outline" onClick={() => void load()}>
          <RefreshCw className="h-4 w-4" />
          {t("settings.retry", "Повторить")}
        </Button>
      </div>
    );
  }

  const dirty =
    form.ollama_url !== settings.backend.ollama_url ||
    form.embedding_model !== settings.backend.embedding_model ||
    form.embedding_batch_size !== settings.backend.embedding_batch_size ||
    form.embedding_retries !== settings.backend.embedding_retries ||
    form.ollama_timeout !== settings.backend.ollama_timeout ||
    form.ollama_connection_timeout !== settings.backend.ollama_connection_timeout ||
    form.max_file_size_mb !== settings.backend.max_file_size_mb ||
    form.max_files_per_request !== settings.backend.max_files_per_request ||
    form.default_chunk_size !== settings.backend.default_chunk_size ||
    form.default_chunk_overlap !== settings.backend.default_chunk_overlap ||
    form.default_structural_max_chunk_size !== settings.backend.default_structural_max_chunk_size ||
    form.default_structural_min_chunk_size !== settings.backend.default_structural_min_chunk_size;

  const dimension = testResult?.dimension ?? settings.ollama.dimension;
  const testModel = form.embedding_model.trim() || "nomic-embed-text";
  const pullCommand = testResult?.pull_command ?? `ollama pull ${testModel}`;

  return (
    <div className="space-y-6">
      {/* Заголовок */}
      <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
        <Settings className="h-6 w-6 text-primary DEFAULT" />
        {t("settings.title", "Настройки")}
      </h1>

      {/* Предупреждение о смене модели */}
      {modelChanged ? (
        <Alert variant="warning" icon={<TriangleAlert className="h-4 w-4" />}>
          {t(
            "settings.modelChangeWarning",
            "Смена модели эмбеддингов потребует пересоздания существующих индексов: добавление векторов в индекс с другой моделью или размерностью запрещено backend'ом.",
          )}
        </Alert>
      ) : null}

      {/* Backend-конфигурация */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4 text-muted-foreground" />
            {t("settings.backendTitle", "Backend-конфигурация")}
          </CardTitle>
          <CardDescription>
            {t(
              "settings.backendDesc",
              "Параметры подключения к Ollama, лимиты загрузки и настройки chunking по умолчанию.",
            )}
          </CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void handleSave();
          }}
        >
          <CardContent className="space-y-5">
            <div className="grid gap-4 md:grid-cols-2">
              <Input
                label={t("settings.url", "URL Ollama")}
                value={form.ollama_url}
                onChange={(e) => setTextField("ollama_url", e.target.value)}
                type="url"
                placeholder="http://localhost:11434"
              />
              <Input
                label={t("settings.embeddingModel", "Модель эмбеддингов")}
                value={form.embedding_model}
                onChange={(e) => setTextField("embedding_model", e.target.value)}
                placeholder="nomic-embed-text"
              />
              <Input
                label={t("settings.batchSize", "Размер batch")}
                type="number"
                min={1}
                value={form.embedding_batch_size}
                onChange={(e) => setNumberField("embedding_batch_size", Number(e.target.value))}
              />
              <Input
                label={t("settings.retries", "Повторные попытки")}
                type="number"
                min={0}
                value={form.embedding_retries}
                onChange={(e) => setNumberField("embedding_retries", Number(e.target.value))}
              />
              <Input
                label={t("settings.ollamaTimeout", "Таймаут Ollama, с")}
                type="number"
                min={1}
                value={form.ollama_timeout}
                onChange={(e) => setNumberField("ollama_timeout", Number(e.target.value))}
              />
              <Input
                label={t("settings.connectionTimeout", "Таймаут соединения, с")}
                type="number"
                min={1}
                value={form.ollama_connection_timeout}
                onChange={(e) => setNumberField("ollama_connection_timeout", Number(e.target.value))}
              />
              <Input
                label={t("settings.maxFileSize", "Лимит файла, МБ")}
                type="number"
                min={1}
                value={form.max_file_size_mb}
                onChange={(e) => setNumberField("max_file_size_mb", Number(e.target.value))}
                hint={formatBytes(form.max_file_size_mb * 1024 * 1024)}
              />
              <Input
                label={t("settings.maxFiles", "Лимит файлов за запрос")}
                type="number"
                min={1}
                value={form.max_files_per_request}
                onChange={(e) => setNumberField("max_files_per_request", Number(e.target.value))}
              />
            </div>

            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t("settings.fixedSizeSection", "Fixed-size")}
              </p>
              <div className="mt-2 grid gap-4 md:grid-cols-2">
                <Input
                  label={t("settings.defaultChunkSize", "Размер чанка по умолчанию")}
                  type="number"
                  min={1}
                  value={form.default_chunk_size}
                  onChange={(e) => setNumberField("default_chunk_size", Number(e.target.value))}
                />
                <Input
                  label={t("settings.defaultChunkOverlap", "Перекрытие чанков по умолчанию")}
                  type="number"
                  min={0}
                  value={form.default_chunk_overlap}
                  onChange={(e) => setNumberField("default_chunk_overlap", Number(e.target.value))}
                />
              </div>
            </div>

            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t("settings.structuralSection", "Structural")}
              </p>
              <div className="mt-2 grid gap-4 md:grid-cols-2">
                <Input
                  label={t("settings.structuralMax", "Макс. размер чанка")}
                  type="number"
                  min={1}
                  value={form.default_structural_max_chunk_size}
                  onChange={(e) => setNumberField("default_structural_max_chunk_size", Number(e.target.value))}
                />
                <Input
                  label={t("settings.structuralMin", "Мин. размер чанка")}
                  type="number"
                  min={1}
                  value={form.default_structural_min_chunk_size}
                  onChange={(e) => setNumberField("default_structural_min_chunk_size", Number(e.target.value))}
                />
              </div>
            </div>
          </CardContent>
          <CardFooter className="gap-2">
            <Button type="submit" variant="default" loading={saving} disabled={!dirty && !saving}>
              <CheckCircle2 className="h-4 w-4" />
              {t("settings.save", "Сохранить")}
            </Button>
            <Button type="button" variant="ghost" onClick={handleReset} disabled={!dirty}>
              {t("settings.reset", "Сбросить")}
            </Button>
          </CardFooter>
        </form>
      </Card>

      {/* Ollama */}
      <Card>
        <CardHeader className="sm:flex-row sm:items-center sm:justify-between sm:space-y-0">
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-muted-foreground" />
            {t("settings.ollamaTitle", "Ollama")}
          </CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refreshStatus()}
            loading={ollamaStatusLoading}
          >
            <RefreshCw className="h-4 w-4" />
            {t("settings.refreshStatus", "Обновить статус")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {ollamaStatus ? (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <Badge variant={ollamaStatus.available ? "success" : "error"}>
                {ollamaStatus.available
                  ? t("settings.ollamaAvailable", "доступен")
                  : t("settings.ollamaUnavailable", "недоступен")}
              </Badge>
              <div>
                <p className="text-xs text-muted-foreground">{t("settings.version", "Версия")}</p>
                <p className="mt-0.5 font-mono text-sm font-medium">{ollamaStatus.version ?? "—"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("settings.model", "Модель")}</p>
                <p className="mt-0.5 font-mono text-sm font-medium">{ollamaStatus.model ?? "—"}</p>
              </div>
              {ollamaStatus.message ? (
                <p className="text-xs text-muted-foreground">{ollamaStatus.message}</p>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t(
                "settings.noStatus",
                "Статус не проверялся. Нажмите «Обновить статус» или «Проверить подключение».",
              )}
            </p>
          )}
          {ollamaStatusError ? (
            <Alert variant="error" icon={<TriangleAlert className="h-4 w-4" />}>
              <span>{t("settings.ollamaStatusError", "Не удалось получить статус Ollama")}</span>
              {ollamaStatusError ? (
                <p className="mt-1 text-xs opacity-80">{ollamaStatusError}</p>
              ) : null}
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => void handleTest()} loading={testing}>
              {t("settings.testConnection", "Проверить подключение")}
            </Button>
          </div>

          {testResult ? (
            <Alert
              variant={testResult.ok ? "success" : "error"}
              icon={testResult.ok ? <CheckCircle2 className="h-4 w-4" /> : <TriangleAlert className="h-4 w-4" />}
            >
              <p className="font-medium">{testResult.message}</p>
              {dimension !== null ? (
                <p className="mt-1 text-xs">
                  {t("settings.dimension", "Размерность вектора: {dim}").replace("{dim}", String(dimension))}
                </p>
              ) : null}
              {testResult.model_available === false ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Kbd>{pullCommand}</Kbd>
                  <Button variant="outline" size="sm" onClick={() => void copyPullCommand(pullCommand)}>
                    <Copy className="h-3.5 w-3.5" />
                    {t("settings.copy", "Копировать")}
                  </Button>
                  {copied ? (
                    <span className="text-xs text-emerald-600 dark:text-emerald-400">
                      {t("settings.copied", "Скопировано")}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {testResult.error ? <p className="mt-1 text-xs opacity-80">{testResult.error}</p> : null}
            </Alert>
          ) : null}
        </CardContent>
      </Card>

      {/* Интерфейс */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {dark ? (
              <Moon className="h-4 w-4 text-muted-foreground" />
            ) : (
              <Sun className="h-4 w-4 text-muted-foreground" />
            )}
            {t("settings.interfaceTitle", "Интерфейс")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <ToggleSwitch
              checked={dark}
              onChange={() => toggle()}
              label={t("settings.darkTheme", "Тёмная тема")}
            />
            <span className="text-xs text-muted-foreground">
              {dark
                ? t("settings.themeDark", "Текущая тема: тёмная")
                : t("settings.themeLight", "Текущая тема: светлая")}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Хранилище */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="h-4 w-4 text-muted-foreground" />
            {t("settings.storageTitle", "Хранилище")}
          </CardTitle>
          <CardDescription>
            {t("settings.storageDesc", "Каталоги и файлы, используемые backend'ом.")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                {t("settings.storageDir", "Каталог данных")}
              </p>
              <code className="mt-1 block break-all rounded border border-border bg-secondary DEFAULT px-2 py-1 font-mono text-xs">
                {settings.storage.dir}
              </code>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                {t("settings.storageCollections", "Каталог коллекций")}
              </p>
              <code className="mt-1 block break-all rounded border border-border bg-secondary DEFAULT px-2 py-1 font-mono text-xs">
                {settings.storage.collections_dir}
              </code>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                {t("settings.storageUploads", "Каталог загрузок")}
              </p>
              <code className="mt-1 block break-all rounded border border-border bg-secondary DEFAULT px-2 py-1 font-mono text-xs">
                {settings.storage.uploads_dir}
              </code>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                {t("settings.storageDb", "Файл базы данных")}
              </p>
              <code className="mt-1 block break-all rounded border border-border bg-secondary DEFAULT px-2 py-1 font-mono text-xs">
                {settings.storage.db_path}
              </code>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Информация о безопасности */}
      <Alert variant="info">
        {t(
          "settings.secretsInfo",
          "Секреты и чувствительные настройки должны храниться в переменных окружения (.env), а не во frontend.",
        )}
      </Alert>
    </div>
  );
}