// Поток NDJSON достройки графа (POST /api/knowledge/v1/graph/build): события
// graph → edge* → notice* → done, по одному JSON в строке. Перенесено из GraphPage.tsx.

export const KNOWLEDGE_API = "/api/knowledge/v1";

export async function* ndjson(response: Response): AsyncGenerator<Record<string, unknown>> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";
    for (const line of parts) if (line.trim()) yield JSON.parse(line);
  }
  if (buffer.trim()) yield JSON.parse(buffer);
}
