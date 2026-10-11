/** Страница «Документы»: загрузка файлов, список документов, текст, переизвлечение, удаление. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CircleAlert,
  Database,
  Eye,
  FileText,
  FileUp,
  RefreshCw,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { t } from "../app/i18n";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  EmptyState,
  Spinner,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { cn, formatBytes, formatNumber } from "../lib/utils";
import {
  deleteDocument,
  extractDocument,
  getDocumentText,
  listDocuments,
  uploadDemoDocuments,
  uploadDocuments,
} from "../services/api";
import type { DocumentOut, DocumentStatus, DocumentText, UploadResponse } from "../types/api";

const ACCEPT =
  ".pdf,.docx,.txt,.md,.mdx,.rst,.py,.js,.jsx,.ts,.tsx,.html,.json,.yml,.yaml,.xml,.csv,.sql,.log";

/** Русская форма множественного числа для слова «файл». */
function filesLabel(n: number): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} файл`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return `${n} файла`;
  return `${n} файлов`;
}

interface StatusInfo {
  variant: "success" | "warning" | "error" | "secondary";
  label: string;
}

function statusInfo(status: DocumentStatus): StatusInfo {
  switch (status) {
    case "ready":
      return { variant: "success", label: t("docs.status.ready", "Готов к индексации") };
    case "indexed":
      return { variant: "success", label: t("docs.status.indexed", "Проиндексирован") };
    case "error":
      return { variant: "error", label: t("docs.status.error", "Ошибка") };
    case "extracting":
      return { variant: "warning", label: t("docs.status.extracting", "Извлечение…") };
    case "indexing":
      return { variant: "secondary", label: t("docs.status.indexing", "Индексация…") };
    default:
      return { variant: "secondary", label: t("docs.status.uploaded", "Загружен") };
  }
}

export function DocumentsPage() {
  const toast = useToast();

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);

  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [textDoc, setTextDoc] = useState<DocumentOut | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<DocumentText | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<DocumentOut | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      setDocuments(await listDocuments());
    } catch (e) {
      setApiError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const addFiles = (incoming: File[]) => {
    if (incoming.length === 0) return;
    setSelectedFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}:${f.lastModified}`));
      const fresh = incoming.filter((f) => !seen.has(`${f.name}:${f.size}:${f.lastModified}`));
      return [...prev, ...fresh];
    });
  };

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const applyUploadResult = (resp: UploadResponse, total: number) => {
    if (resp.uploaded > 0) {
      toast.success(t("docs.uploaded", `Загружено ${resp.uploaded} из ${total}`));
    }
    if (resp.failed > 0) {
      const details = resp.errors
        .map((e) => `${e.filename ?? t("docs.file", "файл")}: ${e.message}`)
        .join("\n");
      if (resp.uploaded > 0) {
        toast.warning(t("docs.uploadPartial", `Загружено не всё: ${resp.failed} из ${total}`), details);
      } else {
        toast.error(t("docs.uploadFailed", "Не удалось загрузить файлы"), details);
      }
    }
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0 || uploading) return;
    const total = selectedFiles.length;
    setUploading(true);
    try {
      const resp = await uploadDocuments(selectedFiles);
      applyUploadResult(resp, total);
      setSelectedFiles([]);
      await loadDocuments();
    } catch (e) {
      toast.error(t("docs.uploadError", "Ошибка загрузки"), e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  const handleUploadDemo = async () => {
    if (uploading) return;
    setUploading(true);
    try {
      const resp = await uploadDemoDocuments();
      applyUploadResult(resp, resp.uploaded + resp.failed);
      await loadDocuments();
    } catch (e) {
      toast.error(
        t("docs.demoUploadError", "Ошибка загрузки демонстрационных документов"),
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setUploading(false);
    }
  };

  const handleExtract = async (doc: DocumentOut) => {
    if (busyId) return;
    setBusyId(doc.id);
    try {
      await extractDocument(doc.id);
      toast.success(t("docs.reExtracted", "Переизвлечение запущено"));
      await loadDocuments();
    } catch (e) {
      toast.error(t("docs.reExtractError", "Ошибка переизвлечения"), e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const openText = async (doc: DocumentOut) => {
    setTextDoc(doc);
    setTextContent(null);
    setTextError(null);
    setTextLoading(true);
    try {
      setTextContent(await getDocumentText(doc.id));
    } catch (e) {
      setTextError(e instanceof Error ? e.message : String(e));
    } finally {
      setTextLoading(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    try {
      await deleteDocument(deleteTarget.id);
      toast.success(t("docs.deleted", "Документ удалён"));
      setDeleteTarget(null);
      await loadDocuments();
    } catch (e) {
      toast.error(t("docs.deleteError", "Ошибка удаления"), e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(false);
    }
  };

  const allWarnings = documents.flatMap((d) => d.warnings.map((w) => `${d.source}: ${w}`));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{t("docs.title", "Документы")}</h1>
        <Button variant="outline" disabled={uploading} onClick={() => void handleUploadDemo()}>
          <Database className="h-4 w-4" />
          {t("docs.uploadDemo", "Загрузить демонстрационные документы")}
        </Button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          addFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />

      <Card>
        <CardContent>
          <div
            className={cn(
              "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragActive
                ? "border-primary bg-primary/5"
                : "border-border bg-card hover:border-primary/60 hover:bg-accent/40",
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragActive(false);
              addFiles(Array.from(e.dataTransfer.files));
            }}
            onClick={() => fileInputRef.current?.click()}
          >
            <FileUp className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm font-medium">
              {t("docs.dropHint", "Перетащите файлы сюда или выберите их вручную")}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("docs.dropFormats", "PDF, DOCX, TXT, Markdown, код и другие текстовые форматы")}
            </p>
            <Button
              size="sm"
              disabled={uploading}
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
            >
              <Upload className="h-4 w-4" />
              {t("docs.selectFiles", "Выбрать файлы")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {selectedFiles.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("docs.selectedTitle", "Выбранные файлы")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Alert variant="info" icon={<CircleAlert className="h-4 w-4" />}>
              {t("docs.nameConflictHint", "При совпадении имён файлов backend автоматически добавит суффикс к имени.")}
            </Alert>
            <ul className="divide-y divide-border">
              {selectedFiles.map((f, i) => (
                <li key={`${f.name}:${f.size}:${f.lastModified}`} className="flex items-center gap-2 py-2">
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate text-sm">{f.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(f.size)}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={uploading}
                    title={t("docs.removeFile", "Убрать файл")}
                    onClick={() => removeFile(i)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button variant="outline" disabled={uploading} onClick={() => setSelectedFiles([])}>
                {t("docs.cancelSelection", "Отменить выбор")}
              </Button>
              <Button loading={uploading} disabled={uploading} onClick={() => void handleUpload()}>
                <Upload className="h-4 w-4" />
                {t("docs.uploadN", `Загрузить ${filesLabel(selectedFiles.length)}`)}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {allWarnings.length > 0 ? (
        <Alert variant="warning" icon={<CircleAlert className="h-4 w-4" />}>
          <p className="font-medium">{t("docs.warningsTitle", "Предупреждения при извлечении")}</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {allWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Alert>
      ) : null}

      {apiError ? (
        <Alert variant="error" icon={<CircleAlert className="h-4 w-4" />}>
          {t("docs.listError", "Не удалось загрузить список документов")}: {apiError}
        </Alert>
      ) : null}

      {loading ? (
        <Card>
          <CardContent>
            <Spinner label={t("docs.loading", "Загрузка документов…")} />
          </CardContent>
        </Card>
      ) : documents.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-6 w-6" />}
          title={t("docs.emptyTitle", "Нет документов — загрузите файлы")}
          description={t("docs.emptyDescription", "Добавьте документы через drag-and-drop или кнопку «Выбрать файлы».")}
          action={
            <Button onClick={() => fileInputRef.current?.click()}>
              <Upload className="h-4 w-4" />
              {t("docs.selectFiles", "Выбрать файлы")}
            </Button>
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("docs.listTitle", "Документы")}{" "}
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                {filesLabel(documents.length)}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0 py-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">{t("docs.col.file", "Файл")}</th>
                    <th className="px-4 py-2.5 font-medium">{t("docs.col.format", "Формат")}</th>
                    <th className="px-4 py-2.5 font-medium">{t("docs.col.size", "Размер")}</th>
                    <th className="px-4 py-2.5 font-medium">{t("docs.col.chars", "Символы")}</th>
                    <th className="px-4 py-2.5 font-medium">{t("docs.col.pages", "Страницы")}</th>
                    <th className="px-4 py-2.5 font-medium">{t("docs.col.status", "Статус")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("docs.col.actions", "Действия")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {documents.map((doc) => {
                    const info = statusInfo(doc.status);
                    const busy = busyId === doc.id || uploading;
                    return (
                      <tr key={doc.id} className="hover:bg-accent/40">
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <div className="min-w-0">
                              <p className="truncate font-medium">{doc.source}</p>
                              {doc.storage_name !== doc.source ? (
                                <p className="truncate text-xs text-muted-foreground">{doc.storage_name}</p>
                              ) : null}
                            </div>
                            {doc.warnings.length > 0 ? (
                              <Badge variant="warning" title={doc.warnings.join("; ")}>
                                !
                              </Badge>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge variant="outline">{doc.file_type}</Badge>
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5">{formatBytes(doc.file_size)}</td>
                        <td className="px-4 py-2.5">{formatNumber(doc.char_count)}</td>
                        <td className="px-4 py-2.5">{formatNumber(doc.page_count)}</td>
                        <td className="px-4 py-2.5">
                          <Badge variant={info.variant}>{info.label}</Badge>
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              title={t("docs.text", "Просмотреть текст")}
                              onClick={() => void openText(doc)}
                            >
                              <Eye className="h-4 w-4" />
                              {t("docs.text", "Текст")}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              loading={busyId === doc.id}
                              title={t("docs.reExtract", "Переизвлечь текст")}
                              onClick={() => void handleExtract(doc)}
                            >
                              <RefreshCw className="h-4 w-4" />
                              {t("docs.reExtract", "Переизвлечь")}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              title={t("docs.delete", "Удалить документ")}
                              onClick={() => setDeleteTarget(doc)}
                            >
                              <Trash2 className="h-4 w-4" />
                              {t("docs.delete", "Удалить")}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Dialog
        open={textDoc !== null}
        onClose={() => setTextDoc(null)}
        title={t("docs.textDialogTitle", "Текст документа")}
        description={textDoc?.source}
        wide
      >
        {textLoading ? (
          <Spinner label={t("docs.textLoading", "Загрузка текста…")} />
        ) : textError ? (
          <Alert variant="error" icon={<CircleAlert className="h-4 w-4" />}>
            {textError}
          </Alert>
        ) : textContent ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {t("docs.charsShort", "Символы")}: {formatNumber(textContent.char_count)}
              {" · "}
              {t("docs.pagesShort", "Страницы")}:{" "}
              {textContent.page_count !== null ? formatNumber(textContent.page_count) : "—"}
              {textContent.truncated ? ` · ${t("docs.truncated", "текст усечён")}` : ""}
            </p>
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted p-3 font-mono text-xs leading-relaxed">
              {textContent.text}
            </pre>
          </div>
        ) : null}
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        title={t("docs.deleteDialogTitle", "Удалить документ?")}
      >
        <p className="text-sm">
          {t("docs.deleteDialogText", "Будет удалён документ")}{" "}
          <span className="font-medium">«{deleteTarget?.source}»</span>
          {t("docs.deleteDialogIrreversible", ". Действие необратимо.")}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" disabled={deleting} onClick={() => setDeleteTarget(null)}>
            {t("docs.cancel", "Отмена")}
          </Button>
          <Button variant="destructive" loading={deleting} onClick={() => void confirmDelete()}>
            <Trash2 className="h-4 w-4" />
            {t("docs.delete", "Удалить")}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
