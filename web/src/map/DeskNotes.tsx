// Записка от руки на столе под листом карты (openspec/changes/synchro-map, «Шрифты»):
// цитата выбранного с источником. Набрана Bad Script (styles/map.css), только здесь. Строки
// приходят готовыми: подписи переводит страница карты. Список «К чтению» снят по правке
// владельца 2026-11-18: ниже кадра его не видно, а пользы от него нет.

export type DeskQuote = { text: string; source: string };

type Props = {
  quote?: DeskQuote | null;
  /** Подпись области записок для чтения с экрана, например «Записки на столе». */
  label?: string;
};

export function DeskNotes({ quote, label }: Props) {
  if (!quote) return null;
  return (
    <div className="desk-notes" role="group" aria-label={label}>
      {/* key по тексту: при смене выбранного записка «кладётся» заново (анимация появления) */}
      <figure className="desk-note desk-note-quote" key={quote.text}>
        <span className="desk-note-pin" aria-hidden="true" />
        {/* кавычки — в строке от страницы: они зависят от языка */}
        <blockquote>{quote.text}</blockquote>
        <figcaption>— {quote.source}</figcaption>
      </figure>
    </div>
  );
}
