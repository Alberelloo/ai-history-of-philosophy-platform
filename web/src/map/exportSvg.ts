// Выгрузка карты изображением. Карта на экране — несколько <svg> (верх, люди с прокруткой,
// низ); в файл они складываются в один рисунок по своим смещениям. Цвета из CSS-переменных
// подставляются вычисленными значениями (приём standalone() из прежней GraphPage), пунктир
// достроенных связей — атрибут stroke-dasharray, он переносится как есть.

const PROPS = [
  "fill",
  "stroke",
  "color",
  "opacity",
  "fill-opacity",
  "stroke-opacity",
  "stroke-width",
  "stroke-dasharray",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "visibility",
  "text-decoration",
];

// Копия элемента с вычисленными стилями: файл выглядит так же вне сайта.
export function standalone<T extends SVGElement>(el: T): T {
  const copy = el.cloneNode(true) as T;
  const source = [el, ...el.querySelectorAll<SVGElement>("*")];
  const target = [copy, ...copy.querySelectorAll<SVGElement>("*")];
  source.forEach((node, i) => {
    const style = window.getComputedStyle(node);
    const out = target[i];
    PROPS.forEach((prop) => {
      const value = style.getPropertyValue(prop);
      if (value) out.style.setProperty(prop, value);
    });
    out.removeAttribute("class");
    out.removeAttribute("tabindex");
  });
  return copy;
}

export type ExportPart = { svg: SVGSVGElement; y: number; height: number };

// Один SVG из частей карты; фон — бумага листа.
export function composeSvg(parts: ExportPart[], width: number, background: string): string {
  const NS = "http://www.w3.org/2000/svg";
  const height = parts.reduce((h, p) => Math.max(h, p.y + p.height), 0);
  const root = document.createElementNS(NS, "svg");
  root.setAttribute("xmlns", NS);
  root.setAttribute("width", String(width));
  root.setAttribute("height", String(height));
  root.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const bg = document.createElementNS(NS, "rect");
  bg.setAttribute("width", "100%");
  bg.setAttribute("height", "100%");
  bg.setAttribute("fill", background);
  root.append(bg);
  parts.forEach((p) => {
    const copy = standalone(p.svg);
    copy.setAttribute("x", "0");
    copy.setAttribute("y", String(p.y));
    copy.setAttribute("width", String(width));
    copy.setAttribute("height", String(p.height));
    root.append(copy);
  });
  return new XMLSerializer().serializeToString(root);
}

export function downloadSvg(text: string, name: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}
