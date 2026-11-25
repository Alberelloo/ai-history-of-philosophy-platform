// Дозагрузка справочника («Показать ещё»): номер следующей страницы — от последней
// загруженной, а не от длины списка. После смены снимка между страницами запись может
// сдвинуться и прийти повтором; повтор убирается, но счёт страниц от этого не «застревает».

export type Paging = { page: number; limit: number; total: number; returned: number };

// Есть ли что дозагружать: последняя страница не пуста и не дошла до конца списка.
export function hasMore(p: Paging): boolean {
  return p.returned > 0 && p.page * p.limit < p.total;
}

export function nextPage(p: Paging): number {
  return p.page + 1;
}

// Новая страница в конец списка без повторов; firstNew — индекс первой добавленной записи.
export function appendPage<T extends { id: string }>(shown: T[], incoming: T[]): { items: T[]; firstNew: number } {
  const seen = new Set(shown.map((i) => i.id));
  return { items: [...shown, ...incoming.filter((i) => !seen.has(i.id))], firstNew: shown.length };
}
