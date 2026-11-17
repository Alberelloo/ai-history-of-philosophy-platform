# Материалы Ф0.2

Все файлы локальные. Внешняя сеть при просмотре макета не требуется.
Общие стили шрифтов: [fonts.css](fonts.css), font-family `Literata` и `Onest`.
Все портреты — в общественном достоянии (Public domain по метаданным Commons), получены
2026-11-14. Исходные сведения: [commons-metadata.json](commons-metadata.json).

| Локальный файл | Автор / источник |
|---|---|
| [kant.jpg](kant.jpg) | Неизвестный, возможно Элизабет фон Штегеман, около 1790; [Commons](https://commons.wikimedia.org/wiki/File:Immanuel_Kant_(painted_portrait).jpg) |
| [hume.jpg](hume.jpg) | Аллан Рэмзи, 1754; [Commons](https://commons.wikimedia.org/wiki/File:Painting_of_David_Hume.jpg) |
| [locke.jpg](locke.jpg) | Годфри Неллер, 1697; [Commons](https://commons.wikimedia.org/wiki/File:John_Locke.jpg) |
| [descartes.jpg](descartes.jpg) | По Франсу Халсу, 1649; [Commons](https://commons.wikimedia.org/wiki/File:Frans_Hals_-_Portret_van_Ren%C3%A9_Descartes.jpg) |

Изображения загружены через Commons Special:FilePath, адаптированы сервером до ~250px.
Оригинальные цвета хранятся локально; представление медальона задаёт дуотон средствами SVG/CSS,
не подменяя историческое изображение выдуманным.

## Шрифты

Копии из установленных пакетов `web/node_modules/@fontsource/onest` (400/500/600)
и `@fontsource-variable/literata` (variable wght). Кириллический и латинский поднаборы.
Лицензии SIL Open Font License: [Onest](onest-LICENSE.txt), [Literata](literata-LICENSE.txt).
Искусственного скачивания из Google Fonts при открытии нет.

## Данные

[fixtures.js](../fixtures.js) загружается обычным script до app.js.
`window.GRAPH_FIXTURES` содержит `genesis`, `specimens`, `dense`,
`window.GRAPH_STATES` — 8 системных сценариев. Все отношения и цитаты в наборах
**демонстрационные**, а не верифицированные исторические утверждения.
Статусы проверяют язык представления, не означают, что вымышленные примеры проверены оператором.

Материалы собраны ведущим после сбоя агента материалов. Продуктовые сервисы не вызывались.
