// Обращения к сервису библиотеки. Типы повторяют ответы /api/v1.

export type SourceItem = {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  language: string;
  kind: "textbook" | "primary" | "reference";
  license: { title: string | null; url: string | null };
};

export type SourceList = {
  sources: SourceItem[];
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
  | { status: "source_unavailable" }
  | { status: "unknown" };

export class ApiError extends Error {
  constructor(
    message: string,
    public kind: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`);
  const body = await response.json();
  if (!response.ok) throw new ApiError(body.error ?? "", body.kind ?? "error", body ?? {});
  return body as T;
}

export const api = {
  sources(params: { kinds: string[]; languages: string[]; query: string }): Promise<SourceList> {
    const search = new URLSearchParams();
    params.kinds.forEach((k) => search.append("kind", k));
    params.languages.forEach((l) => search.append("lang", l));
    if (params.query) search.set("q", params.query);
    return get(`/sources?${search}`);
  },
  current(remembered?: string): Promise<{ source_id: string | null; notice: string | null }> {
    return get(`/current${remembered ? `?remembered=${encodeURIComponent(remembered)}` : ""}`);
  },
  toc: (sourceId: string) => get<TocItem[]>(`/sources/${sourceId}/toc`),
  chapter: (sourceId: string, chapterId: string) =>
    get<Chapter>(`/sources/${sourceId}/chapters/${chapterId}`),
  paragraph: (id: string) => get<Resolved>(`/paragraphs/${id}`),
};
