// Записки от руки на столе под листом карты (openspec/changes/synchro-map, «Шрифты»):
// цитата выбранного с источником и «К чтению» — его труды. Набраны Bad Script (styles/map.css),
// только здесь. Строки приходят готовыми: подписи переводит страница карты.

export type DeskQuote = { text: string; source: string };
export type DeskReading = { title: string; year?: number | string };

type Props = {
  quote?: DeskQuote | null;
  reading?: DeskReading[];
  /** Заголовок списка, например «К чтению». */
  readingTitle: string;
  /** Подпись области записок для чтения с экрана, например «Записки на столе». */
  label?: string;
};

export function DeskNotes({ quote, reading = [], readingTitle, label }: Props) {
  if (!quote && reading.length === 0) return null;
  return (
    <div className="desk-notes" role="group" aria-label={label}>
      {quote && (
        // key по тексту: при смене выбранного записка «кладётся» заново (анимация появления)
        <figure className="desk-note desk-note-quote" key={quote.text}>
          <span className="desk-note-pin" aria-hidden="true" />
          {/* кавычки — в строке от страницы: они зависят от языка */}
          <blockquote>{quote.text}</blockquote>
          <figcaption>— {quote.source}</figcaption>
        </figure>
      )}
      {reading.length > 0 && (
        <section className="desk-note desk-note-reading" key={reading.map((r) => r.title).join("|")}>
          <h2>{readingTitle}</h2>
          <ol>
            {reading.map((item) => (
              <li key={item.title}>
                {item.title}
                {item.year != null && <span className="desk-note-year">, {item.year}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
