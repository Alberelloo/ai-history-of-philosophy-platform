// Все обращения клиента к сервисам. Типы повторяют ответы /api/v1, /api/knowledge/v1, /api/assistant/v1.

export type SourceItem = {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  language: string;
  kind: "textbook" | "primary" | "reference";
  license: { title: string | null; url: string | null };
};

// Источник, закрытый для региона читателя: название, авторы и пометка, без года и лицензии.
export type RestrictedSourceItem = {
  id: string;
  title: string;
  authors: string[];
  restricted: true;
  regions: string[];
};

export type SourceList = {
  sources: (SourceItem | RestrictedSourceItem)[];
  languages: string[];
  default_source_id: string | null;
};

export type TocItem = {
  id: string;
  title: string;
  level: number;
  chapter_id: string | null;
  children: TocItem[];
};

export type ChapterBlock =
  | { type: "heading"; section_id: string; text: string; level: number }
  | {
      type: "block";
      id: string;
      kind: "paragraph" | "quote" | "verse" | "list" | "unrendered";
      text: string;
      lang: string;
      pages: [number, string][];
      notes: [number, string][];
      detail: string | null;
      detail_code: string | null;
      page: string | null;
    };

export type Footnote = { marker: string; text: string; linked: boolean };

export type Chapter = {
  source_id: string;
  chapter_id: string;
  title: string;
  blocks: ChapterBlock[];
  footnotes: Record<string, Footnote>;
  unlinked_notes: Footnote[];
  previous: string | null;
  next: string | null;
  first: string;
  anchor: string | null; // адрес указывал на раздел внутри главы
};

export type Resolved =
  | { status: "found"; source_id: string; chapter_id: string; paragraph_id: string }
  | { status: "removed"; source_id: string; chapter_id: string | null }
  | {
      status: "source_unavailable";
      reason?: "region";
      source?: { id: string; title: string; authors: string[] };
    }
  | { status: "unknown" };

// Базы сервисов: шлюз проксирует /api/<сервис>/v1 к своему сервису (библиотека — /api/v1).
export const BASES = {
  library: "/api/v1",
  knowledge: "/api/knowledge/v1",
  assistant: "/api/assistant/v1",
} as const;

// Ответ сервиса не ``ok``: код ошибки (``kind``), HTTP-статус и тело ответа (``details``) —
// в нём бывают поля сверх ``error``/``kind`` (``first_chapter_id``, ``suggestions``, ``reason``).
// Сбой сети и отмена запроса (``AbortError``) сюда не заворачиваются: вызывающий код отличает
// отмену по ``signal.aborted``.
export class ApiError extends Error {
  constructor(
    message: string,
    public kind: string,
    public details: Record<string, unknown> = {},
    public status = 0,
  ) {
    super(message);
  }
}

type Json = Record<string, unknown>;
type RequestOptions = { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal };

// Запрос к сервису: ответ не ``ok`` — ``ApiError`` с разобранным телом (не JSON — пустое тело).
export async function request(url: string, options: RequestOptions = {}): Promise<Response> {
  const response = await fetch(url, {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    signal: options.signal,
    ...(options.body === undefined
      ? {}
      : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(options.body) }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Json;
    const details = body && typeof body === "object" ? body : {};
    throw new ApiError(
      typeof details.error === "string" ? details.error : "",
      typeof details.kind === "string" ? details.kind : "error",
      details,
      response.status,
    );
  }
  return response;
}

async function json<T>(url: string, options?: RequestOptions): Promise<T> {
  return (await (await request(url, options)).json()) as T;
}

// Поток NDJSON: события по одному JSON в строке; хвост без перевода строки — последнее событие.
export async function* ndjson(response: Response): AsyncGenerator<Json> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";
    for (const line of parts) if (line.trim()) yield JSON.parse(line) as Json;
  }
  if (buffer.trim()) yield JSON.parse(buffer) as Json;
}

// Запрос с ответом-потоком: ошибка до начала потока — ``ApiError``, затем события по одному.
export async function* stream(url: string, options?: RequestOptions): AsyncGenerator<Json> {
  yield* ndjson(await request(url, options));
}

const lib = (path: string) => `${BASES.library}${path}`;
const kn = (path: string) => `${BASES.knowledge}${path}`;
const query = (params: Record<string, string | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && search.set(k, v));
  const text = search.toString();
  return text ? `?${text}` : "";
};

// Сервис библиотеки.
export const api = {
  sources(params: { kinds: string[]; languages: string[]; query: string }): Promise<SourceList> {
    const search = new URLSearchParams();
    params.kinds.forEach((k) => search.append("kind", k));
    params.languages.forEach((l) => search.append("lang", l));
    if (params.query) search.set("q", params.query);
    return json(lib(`/sources?${search}`));
  },
  current(remembered?: string): Promise<{ source_id: string | null; notice: string | null }> {
    return json(lib(`/current${remembered ? `?remembered=${encodeURIComponent(remembered)}` : ""}`));
  },
  toc: (sourceId: string) => json<TocItem[]>(lib(`/sources/${sourceId}/toc`)),
  chapter: (sourceId: string, chapterId: string) =>
    json<Chapter>(lib(`/sources/${sourceId}/chapters/${chapterId}`)),
  paragraph: (id: string) => json<Resolved>(lib(`/paragraphs/${id}`)),
};

// Сервис знаний. Типы карточек, карты и очереди проверки описаны у компонентов, которые их
// показывают, поэтому методы с такими ответами параметризованы типом.
export const knowledgeApi = {
  card: <T>(entityId: string, params: URLSearchParams, signal?: AbortSignal) =>
    json<T>(kn(`/entities/${entityId}/card?${params}`), { signal }),
  // Описание без сохранённого текста дописывается потоком (delta/done).
  description: (entityId: string, generation: boolean, signal?: AbortSignal) =>
    stream(kn(`/entities/${entityId}/description?generation=${generation}`), { method: "POST", signal }),
  mentions: <T>(targets: string[], signal?: AbortSignal) =>
    json<T>(kn(`/mentions?targets=${targets.map(encodeURIComponent).join(",")}`), { signal }),
  map: <T>(params: { textbook?: string; onlyTextbook?: boolean }) =>
    json<T>(kn(`/map${query({ textbook: params.textbook, only_textbook: params.onlyTextbook ? "true" : undefined })}`)),
  edge: <T>(id: string, textbook?: string) =>
    json<T>(kn(`/graph/edges/${encodeURIComponent(id)}${textbook ? `?textbook=${encodeURIComponent(textbook)}` : ""}`)),
  // Достройка связей потоком: graph → edge* → notice* → done.
  build: (body: Json) => stream(kn("/graph/build"), { body }),
  // Проверка оператора: без входа сервис отвечает 404.
  login: (password: string) => request(kn("/operator/login"), { body: { password } }),
  reviewQueue: <T>(kind: string) => json<T>(kn(`/review/queue${kind ? `?kind=${kind}` : ""}`)),
  reviewStatement: <T>(id: string) => json<T>(kn(`/review/statements/${id}`)),
  decide: (id: string, decision: string, changes?: Json) =>
    request(kn(`/review/statements/${id}`), { body: { decision, changes } }),
  duplicate: (itemId: number, merge: boolean) =>
    request(kn(`/review/items/${itemId}/duplicate?merge=${merge}`), { method: "POST" }),
  proposal: (proposalId: number, accept: boolean) =>
    request(kn(`/review/proposals/${proposalId}?accept=${accept}`), { method: "POST" }),
  portraits: <T>(status: string) => json<T>(kn(`/review/portraits?status=${status}`)),
  // Адрес изображения портрета для <img>: не запрос, а ссылка.
  portraitUrl: (id: number) => kn(`/portraits/${id}`),
  portraitAction: (id: number, action: string) =>
    request(kn(`/review/portraits/${id}?action=${action}`), { method: "POST" }),
};

// Ассистент: ответ потоком событий (stage, fragment, suggestion, handoff, notice, done, error).
export const assistantApi = {
  ask: (body: Json, signal: AbortSignal) => stream(`${BASES.assistant}/ask`, { body, signal }),
};
