import type { ReactNode } from "react";
import { useT } from "./i18n";

// Обёртки над компонентами дизайн-системы (docs/design/system/components.css, классы pg-*).
// Значки — свой набор: сетка 24px, штрих 1.5px, краска currentColor.

const ICONS = {
  chat: (
    <>
      <path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5Z" />
      <path d="M8 9.5h8M8 12.5h5" />
    </>
  ),
  expand: <path d="M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5 13 11M4.5 19.5 11 13" />,
  graph: (
    <>
      <circle cx="6.5" cy="16.5" r="2.5" />
      <circle cx="17.5" cy="7.5" r="2.5" />
      <circle cx="17.5" cy="17" r="2" />
      <path d="m8.4 14.8 7.2-5.6M9 16.7h6.5" />
    </>
  ),
  close: <path d="M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  book: (
    <>
      <path d="M3.5 6c2.8-1.2 5.6-1 8.5 1 2.9-2 5.7-2.2 8.5-1v12c-2.8-1.2-5.6-1-8.5 1-2.9-2-5.7-2.2-8.5-1Z" />
      <path d="M12 7v12" />
    </>
  ),
  diamond: <path d="M12 4.5 19.5 12 12 19.5 4.5 12Z" />,
  scales: (
    <>
      <path d="M12 5v14M7.5 19h9M5 8.5h14" />
      <path d="m7 8.5-2.5 5h5Z" />
      <path d="m17 8.5-2.5 5h5Z" />
    </>
  ),
  warning: (
    <>
      <path d="M12 4.5 20.5 19h-17Z" />
      <path d="M12 10v4" />
      <path d="M12 16.6v.4" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5M12 8v.01" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" />
    </>
  ),
  moon: <path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10Z" />,
  system: (
    <>
      <rect x="3.5" y="5" width="17" height="11.5" rx="1.5" />
      <path d="M9 19.5h6M12 16.5v3" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m15.5 15.5 4 4" />
    </>
  ),
  chevronRight: <path d="m9.5 6 6 6-6 6" />,
  chevronDown: <path d="m6 9.5 6 6 6-6" />,
  arrowLeft: <path d="M19 12H5.5M11 6l-6 6 6 6" />,
  arrowRight: <path d="M5 12h13.5M13 6l6 6-6 6" />,
  link: (
    <>
      <path d="M10 14a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1 1" />
      <path d="M14 10a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1-1" />
    </>
  ),
  download: <path d="M12 4.5v11M7 11l5 5 5-5M5 19.5h14" />,
  plus: <path d="M12 5.5v13M5.5 12h13" />,
  minus: <path d="M5.5 12h13" />,
  stop: <rect x="7" y="7" width="10" height="10" rx="1.5" />,
  copy: (
    <>
      <rect x="8.5" y="8.5" width="11" height="11" rx="1.5" />
      <path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" />
    </>
  ),
  retry: <path d="M5 12a7 7 0 1 0 2.1-5M5 4.5V9h4.5" />,
  newDialog: (
    <>
      <path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5Z" />
      <path d="M12 8v6M9 11h6" />
    </>
  ),
};

export type IconName = keyof typeof ICONS;

export function Icon({ name, small, className }: { name: IconName; small?: boolean; className?: string }) {
  return (
    <svg
      className={["pg-ico", small ? "pg-ico--sm" : "", className ?? ""].filter(Boolean).join(" ")}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      {ICONS[name]}
    </svg>
  );
}

// Знак PhiloGraph: ось времени, два узла и дуга влияния между ними.
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg className="pg-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path d="M4 26.5h24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      <path d="M9.5 26.5v2.25M22.5 26.5v2.25" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path
        d="M10.9 14.6C12.6 8.2 17.4 6.4 20.3 8.9"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="9.5" cy="18" r="3.75" fill="currentColor" />
      <circle cx="22.5" cy="11" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

// Переключатель: настройка действует сразу; вся строка — подпись.
export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled,
  title,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <label className={disabled ? "pg-switch is-disabled" : "pg-switch"} title={title}>
      <input
        className="pg-switch__input"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="pg-switch__text">
        {label}
        {hint && <span className="pg-switch__hint">{hint}</span>}
      </span>
    </label>
  );
}

export type SegItem<T extends string> = { value: T; label: string; icon?: IconName; iconOnly?: boolean };

// Сегментный переключатель: каждый вариант — кнопка с aria-pressed, группа подписана.
export function Seg<T extends string>({
  label,
  items,
  value,
  onChange,
  className,
}: {
  label: string;
  items: SegItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={["pg-seg", className ?? ""].filter(Boolean).join(" ")} role="group" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          className={item.iconOnly ? "pg-seg__item pg-seg__item--icon" : "pg-seg__item"}
          aria-pressed={item.value === value}
          aria-label={item.iconOnly ? item.label : undefined}
          title={item.iconOnly ? item.label : undefined}
          onClick={() => onChange(item.value)}
        >
          {item.icon && <Icon name={item.icon} small />}
          {!item.iconOnly && item.label}
        </button>
      ))}
    </div>
  );
}

// Пометка «сгенерировано» внутри текста: ромб, тёплый фон, пунктир.
export function GeneratedMark({ label }: { label?: string }) {
  const t = useT();
  return (
    <svg
      className="pg-generated__mark ungrounded-mark"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      role="img"
      aria-label={label ?? t.status.generated}
    >
      <title>{label ?? t.status.generated}</title>
      <path d="M12 4.5 19.5 12 12 19.5 4.5 12Z" />
    </svg>
  );
}

export function Generated({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return (
    <span className={["pg-generated", className ?? ""].filter(Boolean).join(" ")}>
      <GeneratedMark label={label} />
      {children}
    </span>
  );
}

type Status = "verified" | "sourced" | "generated" | "disputed" | "contradiction";
const STATUS_ICON: Record<Status, IconName> = {
  verified: "check",
  sourced: "book",
  generated: "diamond",
  disputed: "scales",
  contradiction: "warning",
};

export function StatusMark({ status, children, iconOnly }: { status: Status; children?: ReactNode; iconOnly?: boolean }) {
  const t = useT();
  const name = t.status[status];
  const classes = ["pg-status"];
  if (status === "verified") classes.push("pg-status--verified");
  if (status === "generated") classes.push("pg-status--generated");
  if (status === "contradiction") classes.push("pg-status--contradiction");
  if (iconOnly) classes.push("pg-status--icon-only");
  return (
    <span className={classes.join(" ")} title={iconOnly ? name : undefined} role={iconOnly ? "img" : undefined} aria-label={iconOnly ? name : undefined}>
      <Icon name={STATUS_ICON[status]} small />
      {!iconOnly && (children ?? name)}
    </span>
  );
}

// Семья сущности: цвет и форма значка в метках, упоминаниях и на графе.
export type Family = "people" | "ideas" | "teachings" | "texts" | "history";
const FAMILIES: Record<string, Family> = {
  person: "people",
  group: "people",
  term: "ideas",
  concept: "ideas",
  conception: "ideas",
  doctrine: "teachings",
  problem: "teachings",
  position: "teachings",
  argument: "teachings",
  work: "texts",
  source: "texts",
  event: "history",
  idea_event: "history",
  phenomenon: "history",
  epoch: "history",
  place: "history",
};

export function familyOf(type: string | null | undefined): Family | undefined {
  return type ? FAMILIES[type] : undefined;
}

export function monogram(name: string): string {
  const words = name
    .replace(/[«»"()]/g, " ")
    .split(/\s+/)
    .filter((w) => /^\p{L}/u.test(w));
  const letters = words.length > 1 ? [words[0], words[words.length - 1]] : words.slice(0, 1);
  return letters.map((w) => w[0].toUpperCase()).join("");
}

// Медальон персоны. Изображений пока нет — монограмма шрифтом чтения со штриховкой.
export function Portrait({ name, size = 56 }: { name: string; size?: number }) {
  const t = useT();
  return (
    <div className="pg-portrait pg-portrait--empty" style={{ ["--size" as string]: `${size}px` }}>
      <div className="pg-portrait__disc" role="img" aria-label={t.card.noImage(name)}>
        {monogram(name)}
      </div>
    </div>
  );
}
