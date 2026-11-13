# Пилотный список персон и портретов (теория познания)

Изменение: `portrait-sourcing`, задача 2.3 «Пилотные данные».
Дата сбора: 2026-11-13. Ветка `claude/portrait-sourcing`.
Все значения взяты из ответов API Wikidata и Wikimedia Commons (см. раздел «Как проверялось»); ничего не заполнено по памяти. Бинарные файлы не скачивались — только метаданные и ссылки.

Состав: 15 персон ядра раздела «теория познания», имена сверены с `docs/product/ontology.md` (раздел 5.3 «Люди и сообщества», сквозной пример §8); в `openspec/specs/ontology-entities/spec.md` форма имён показана на примере «Юм»/«Хьюм». У всех 15 в Wikidata есть `P18`, у всех — категория Commons (`P373`).

Нормализованные коды лицензий: `pd`, `cc0`, `cc-by-<версия>`, `cc-by-sa-<версия>`. Разрешены `pd`, `cc0`, `cc_by`, `cc_by_sa` (см. `openspec/changes/portrait-sourcing/specs/entity-portraits/spec.md`, требование «Лицензии и атрибуция»).

## 1. Таблица кандидатов (P18)

| № | Персона (онтология) | QID | Файл Commons (`P18`) | Страница файла | Автор (`Artist`) | Год (`DateTimeOriginal`) | Лицензия (короткое имя → код) | width×height | MIME | Решение |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Платон | Q859 | `Plato Silanion Musei Capitolini MC1377.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Plato_Silanion_Musei_Capitolini_MC1377.jpg) | Marie-Lan Nguyen (фото, 2009); скульптура — Силанион | 2009 (фото) | CC BY 2.5 → `cc-by-2.5` | 2400×3600 | image/jpeg | принято |
| 2 | Аристотель | Q868 | `Aristotle Altemps Inv8575.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Aristotle_Altemps_Inv8575.jpg) | After Lysippos | after 330 BC | Public domain → `pd` | 1700×2275 | image/jpeg | принято |
| 3 | Аврелий Августин | Q8018 | `Saint Augustine by Philippe de Champaigne.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Saint_Augustine_by_Philippe_de_Champaigne.jpg) | Philippe de Champaigne | между ок. 1645 и ок. 1650 | Public domain → `pd` | 3135×4000 | image/jpeg | принято |
| 4 | Рене Декарт | Q9191 | `Frans Hals - Portret van René Descartes.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Frans_Hals_-_Portret_van_Ren%C3%A9_Descartes.jpg) | After Frans Hals | 1649 | Public domain → `pd` | 817×1000 | image/jpeg | принято |
| 5 | Бенедикт Спиноза | Q35802 | `Spinoza.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Spinoza.jpg) | anonymous | 1665 | Public domain → `pd` | 1377×1600 | image/jpeg | принято |
| 6 | Джон Локк | Q9353 | `JohnLocke.png` | [Commons](https://commons.wikimedia.org/wiki/File:JohnLocke.png) | Godfrey Kneller | 1697 | Public domain → `pd` | 984×1138 | image/png | принято |
| 7 | Готфрид Вильгельм Лейбниц | Q9047 | `Christoph Bernhard Francke - Bildnis des Philosophen Leibniz (ca. 1695).jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Christoph_Bernhard_Francke_-_Bildnis_des_Philosophen_Leibniz_(ca._1695).jpg) | Christoph Bernhard Francke | 1695 | Public domain → `pd` | 4486×5538 | image/jpeg | принято (4.4 МБ — проверить лимит файла) |
| 8 | Джордж Беркли | Q82049 | `George Berkeley by Jonh Smibert.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:George_Berkeley_by_Jonh_Smibert.jpg) | John Smibert | ок. 1728–1730 | Public domain → `pd` | 255×350 | image/jpeg | принято с оговоркой: разрешение мало для карточки, рекомендована замена (см. §2) |
| 9 | Дэвид Юм | Q37160 | `David Hume Ramsay.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:David_Hume_Ramsay.jpg) | Allan Ramsay | 1766 | Public domain → `pd` | 5384×6518 | image/jpeg | принято (22.2 МБ — проверить лимит файла) |
| 10 | Иммануил Кант | Q9312 | `Immanuel Kant - Gemaelde 2.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Immanuel_Kant_-_Gemaelde_2.jpg) | Becker | 1768 | Public domain → `pd` | 940×1640 | image/jpeg | принято |
| 11 | Георг Вильгельм Фридрих Гегель | Q9235 | `Jakob Schlesinger - Hegel 1831.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Jakob_Schlesinger_-_Hegel_1831.jpg) | Jakob Schlesinger | 1831 | Public domain → `pd` | 1654×2085 | image/jpeg | принято |
| 12 | Франц Брентано | Q57196 | `Franz Brentano.jpeg` | [Commons](https://commons.wikimedia.org/wiki/File:Franz_Brentano.jpeg) | `user:svencb` (загрузивший; автор работы не указан) | не указан | Public domain → `pd` | 279×400 | image/jpeg | отказ: слишком мал (279×400), автор и дата не указаны; замена — см. §2 |
| 13 | Эдмунд Гуссерль | Q58586 | `Edmund Husserl 1910s.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Edmund_Husserl_1910s.jpg) | Unknown (Mondadori Publishers) | 1910-е | Public domain → `pd` | 1689×2421 | image/jpeg | принято с оговоркой: скан из Getty Images (Mondadori), происхождение стоит перепроверить |
| 14 | Людвиг Витгенштейн | Q9391 | `Ludwig Wittgenstein.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Ludwig_Wittgenstein.jpg) | Moritz Nähr | 1930 | Public domain → `pd` | 4984×7286 | image/jpeg | принято (8.8 МБ — проверить лимит файла) |
| 15 | Бертран Рассел | Q33760 | `Bertrand Russell photo.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:Bertrand_Russell_photo.jpg) | Bassano Ltd | 1936-10-23 | Public domain → `pd` | 800×630 | image/jpeg | принято с оговоркой: в `Credit` Commons предупреждает о сторонних притязаниях на копирайт |

Итог по P18: 15 из 15 найдены; принято 14 (из них 6 с оговорками по качеству, размеру или происхождению — Беркли, Гуссерль, Рассел, Лейбниц, Юм, Витгенштейн), отклонено 1 по качеству и атрибуции (Брентано); ещё один отказ — по лицензии среди альтернатив (§2). Ни у одной персоны нет статуса «не проверено».

## 2. Отказы и почему

Отказов по лицензии среди `P18` пилота нет: все 15 основных изображений помечены на Commons как Public domain или CC BY, у каждого есть страница файла. Отказы и замены ниже — по разрешению, атрибуции и лицензиям альтернативных кандидатов, которые я проверил в категориях Commons.

| Файл | Персона | Что не так | Причина отказа словами |
|---|---|---|---|
| `Kant, Emmanuel CIPA0720.jpg` ([Commons](https://commons.wikimedia.org/wiki/File:Kant,_Emmanuel_CIPA0720.jpg)) | Кант | `LicenseShortName` = «Licence Ouverte» (Etalab), 1802×2408, ссылка на страницу есть | Лицензия не входит в разрешённый список (общественное достояние, CC0, CC BY, CC BY-SA) и не распознаётся фильтром как одна из `pd`/`cc0`/`cc-by-*`/`cc-by-sa-*` — по спецификации не сохраняется |
| `Franz Brentano.jpeg` ([Commons](https://commons.wikimedia.org/wiki/File:Franz_Brentano.jpeg)) | Брентано | 279×400, `Artist` = имя загрузившего, даты нет | Основное изображение Wikidata слишком мало для карточки и галереи, автор работы не установлен — как главный портрет не годится |
| `George Berkeley by Jonh Smibert.jpg` ([Commons](https://commons.wikimedia.org/wiki/File:George_Berkeley_by_Jonh_Smibert.jpg)) | Беркли | 255×350 | Разрешение меньше, чем у доступной свободной альтернативы (1765×2480); лицензия при этом допустима, поэтому это замена по качеству, а не лицензионный отказ |
| `Hegel 042.jpg` ([Commons](https://commons.wikimedia.org/wiki/File:Hegel_042.jpg)) и кадрированная версия `Hegel 042 (cropped).jpg` | Гегель | одна и та же фотография, два файла | Дубль по композиции: при отборе должен остаться один файл (требование «Отбор портретов персоны», сценарий про дубли) |
| `35. Portrait of Wittgenstein.jpg`, `36. Portrait of Ludwig Wittgenstein, 1930.jpg`, `Wittgenstein by Moritz Nähr.jpg` | Витгенштейн | фотография Moritz Nähr, ок. 1928–1930, три файла в разных кадрированиях | Дубль: разные сканы одного снимка; нужен один (dHash-дедупликация) |
| `Franz Brentano Portrait, 1890.png` и `Franz Brentano, 1890.png` | Брентано | две близкие версии одного снимка 1890 года (737×1231 и 724×1227) | Дубль: выбирать один, второй отбрасывать |

Замены, которые предлагаю внести в манифест вместо отклонённых:

| Персона | Предлагаемый файл | Страница | Автор | Год | Лицензия | Размер |
|---|---|---|---|---|---|---|
| Франц Брентано | `Franz Brentano in Vienna, 1875.png` | [Commons](https://commons.wikimedia.org/wiki/File:Franz_Brentano_in_Vienna,_1875.png) | Fritz Luckhardt | 1875 | Public domain → `pd` | 728×1218 |
| Джордж Беркли | `George Berkeley (1685-1753), Protestant Bishop of Cloyne and Philosopher P6708.jpg` | [Commons](https://commons.wikimedia.org/wiki/File:George_Berkeley_(1685-1753),_Protestant_Bishop_of_Cloyne_and_Philosopher_P6708.jpg) | John Brooks, после James Latham | не указан | Public domain → `pd` | 1765×2480 |

## 3. Нет изображения в Wikidata

Ни у одной из 15 персон пилота такой ситуации нет: у всех есть `P18`, и он разрешён по лицензии (с оговорками из §1). Поэтому персон со статусом «нет изображения» в этом наборе нет.

Если такой случай встретится на следующем шаге (расширение на остальных персон), порядок поиска:

1. `P18` отсутствует → взять категорию Commons из `P373` (у всех 15 она есть, например `Category:Immanuel Kant`), оттуда `list=categorymembers&cmtype=file` и метаданные через `imageinfo`.
2. Категория есть, но файлов-портретов нет → искать в подкатегориях вида `Category:Portraits of <Имя>` (для Гегеля, Витгенштейна, Рассела, Декарта такие категории существуют; для Канта и Гуссерля — пустые ответы API).
3. Ничего не нашлось → оставить монограмму и не подставлять изображение из другого источника; в манифесте персона просто без кандидатов.

## 4. Проверка идентичности персон

Метка и описание — из `wbgetentities` (`props=labels|descriptions`), годы — из `wdt:P569` / `wdt:P570` в Wikidata Query Service. Все QID подтверждены как философы с ожидаемыми годами; ни один не является однофамильцем, растением или астероидом (проверены и отброшены, например, `Q358` — «heritage site», `Q935` — Ньютон, `Q820` — президент Чили, `Q159203` — растение, `Q157342` — астероид).

| Персона (онтология) | QID | Метка Wikidata (ru) | Годы жизни (P569–P570) | Описание (en) |
|---|---|---|---|---|
| Платон | Q859 | Платон | 428 до н. э. – 348 до н. э. | 4th-century BCE Greek philosopher |
| Аристотель | Q868 | Аристотель | 383 до н. э. – 321 до н. э. | Greek philosopher |
| Аврелий Августин | Q8018 | Аврелий Августин | 354-11-14 – 430-08-29 | Christian theologian, philosopher, and saint (354–430) |
| Рене Декарт | Q9191 | Рене Декарт | 1596-03-31 – 1650-02-11 | French philosopher, mathematician, and scientist (1596–1650) |
| Бенедикт Спиноза | Q35802 | Бенедикт Спиноза | 1632-11-24 – 1677-02-21 | Dutch philosopher (1632–1677) |
| Джон Локк | Q9353 | Джон Локк | 1632-09-08 – 1704-11-08 | English philosopher and physician (1632-1704) |
| Готфрид Вильгельм Лейбниц | Q9047 | Готфрид Вильгельм Лейбниц | 1646-07-01 – 1716-11-14 | German mathematician and philosopher (1646–1716) |
| Джордж Беркли | Q82049 | Джордж Беркли | 1685-03-12 – 1753-01-14 | Irish idealist philosopher and Anglican bishop (1685–1753) |
| Дэвид Юм | Q37160 | Дэвид Юм | 1711-05-07 – 1776-08-25 | Scottish philosopher, economist, and historian (1711-1776) |
| Иммануил Кант | Q9312 | Иммануил Кант | 1724-04-22 – 1804-02-12 | German philosopher (1724-1804) |
| Георг Вильгельм Фридрих Гегель | Q9235 | Георг Вильгельм Фридрих Гегель | 1770-08-27 – 1831-11-14 | German philosopher and theologian (1770–1831) |
| Франц Брентано | Q57196 | Франц Брентано | 1838-01-16 – 1917-03-17 | German philosopher and psychologist as well as refounder of the theory of intentionality (1838–1917) |
| Эдмунд Гуссерль | Q58586 | Эдмунд Густав Альбрехт Гуссерль | 1859-04-08 – 1938-04-27 | German philosopher, known as the father of phenomenology (1859–1938) |
| Людвиг Витгенштейн | Q9391 | Людвиг Витгенштейн | 1889-04-26 – 1951-04-29 | Austrian philosopher and logician (1889–1951) |
| Бертран Рассел | Q33760 | Бертран Рассел | 1872-05-18 – 1970-02-02 | British philosopher and logician (1872–1970) |

Замечание по именам: метки Wikidata длиннее, чем имена в онтологии («Бенедикт Спиноза» при «Спиноза» в текстах, «Эдмунд Густав Альбрехт Гуссерль» при «Гуссерль»). Для сущностей онтологии использовать краткую форму, QID — как внешний идентификатор, полную метку — как один из вариантов названия (`docs/product/ontology.md`, §10.1).

## 5. Категории Commons (`P373`)

Все 15 персон имеют `P373`; категории использованы для поиска альтернатив и дублей:

Платон → `Plato`; Аристотель → `Aristotle`; Августин → `Augustinus`; Декарт → `René Descartes`; Спиноза → `Benedictus de Spinoza`; Локк → `John Locke`; Лейбниц → `Gottfried Wilhelm Leibniz`; Беркли → `George Berkeley`; Юм → `David Hume`; Кант → `Immanuel Kant`; Гегель → `Georg Wilhelm Friedrich Hegel`; Брентано → `Franz Brentano`; Гуссерль → `Edmund Husserl`; Витгенштейн → `Ludwig Wittgenstein`; Рассел → `Bertrand Russell`.

## 6. Где данные вызывают сомнение

1. **`license_url` у файлов в общественном достоянии отсутствует.** У всех 15 основных изображений `LicenseShortName` = «Public domain», но `LicenseUrl` в `extmetadata` нет (он есть только у CC-файлов, например у Платона). А спецификация требует хранить адрес лицензии для каждого изображения. Варианты: подставлять адрес шаблона `https://commons.wikimedia.org/wiki/Template:PD-old` / страницы `Commons:Public domain` или оставлять `license_url` пустым и ослабить требование. Нужно решение владельца.
2. **Рассел, `Bertrand Russell photo.jpg`:** Commons в поле `Credit` предупреждает, что третьи стороны заявляли права на исходник (скан Bassano Ltd, 1936). Для пилота допустимо, но в очереди проверки оператору стоит показать предупреждение.
3. **Гуссерль, `Edmund Husserl 1910s.jpg`:** `Artist` = «Unknown (Mondadori Publishers)», `Credit` ведёт на Getty Images. PD по дате, но провенанс скана не прозрачен; рекомендую перепроверить перед подтверждением.
4. **Брентано и Беркли (P18):** 279×400 и 255×350 — меньше типичного размера карточки; предлагаю замены из §2, но замены не проверены на дубли с P18 (визуально это другие фотографии/портреты, dHash должен их различить).
5. **Размер файлов:** Юм — 22.2 МБ (5384×6518), Лейбниц — 4.4 МБ, Витгенштейн — 8.8 МБ. Ресайз до 480 px по спецификации обязателен, но нужен явный лимит на исходную загрузку, иначе `sync` будет тянуть десятки мегабайт.
6. **Дубли по композиции:** у Декарта в категории соседствуют картина «After Frans Hals», гравюра Эделинка «after Frans Hals» и копия из музея в Шалоне — dHash может не поймать гравюру как дубль картины; при отборе проверять вручную или поднимать порог.
7. **Даты создания античных портретов:** у Аристотеля `DateTimeOriginal` = «after 330 BC», у Платона год 2009 относится к фотографии, а не к скульптуре. В подписи карточки год нужно трактовать как дату изображения и не выдавать за дату портрета; для античных бюстов лучше хранить «дата снимка» и «дата оригинала» раздельно (в схеме `portraits` поля только одно — `year`). Это расхождение со спецификацией стоит зафиксировать.

## 7. Решения Lead по итогам исследования (2026-11-13)

1. **Пилот — 13 персон.** Из набора исключены до проверки провенанса:
   Бертран Рассел (`Q33760`, Commons предупреждает о сторонних притязаниях на исходник)
   и Эдмунд Гуссерль (`Q58586`, скан Mondadori/Getty с неясным происхождением).
   Монограмма для них остаётся штатным состоянием; вернуть можно отдельным решением,
   когда провенанс проверен.
2. **Замены принимаются:** Брентано — `Franz Brentano in Vienna, 1875.png` (Luckhardt, PD),
   Беркли — `George Berkeley (1685-1753)... P6708.jpg` (Brooks после Latham, PD).
   Основные `P18` этих персон отклоняются по качеству (279×400 и 255×350).
3. **`license_url` необязателен.** У общественного достояния Commons часто не отдаёт адрес
   лицензии: поле остаётся пустым, в подписи лицензия показывается без ссылки. Требование
   и дизайн обновлены.
4. **Скачиваем эскиз, не оригинал.** `imageinfo` запрашивается с `iiurlwidth=480`, берётся
   `thumburl`; предел — 8 МБ на файл, больше — отказ `too-large`. Это закрывает Юма (22 МБ)
   и Витгенштейна (8,8 МБ).
5. **MIME — по сигнатуре байтов**, а не по расширению: у Локка PNG; значение хранится
   в таблице `portraits` и используется при раздаче.
6. **`year` — свободная строка как в источнике** («1790», «after 330 BC», «2009 (фото)»):
   это подпись, а не дата жизни; не интерпретируем и не приводим к числу.
7. **Дубли по композиции** (гравюра с картины) dHash может не поймать — такие случаи
   остаются на проверку оператором; дубли сканов ловит dHash.

## 8. Как проверялось

Все запросы — `web_fetch` (GET, JSON) к публичным API, 2026-11-13, без скачивания файлов.

1. **Поиск QID:** `https://www.wikidata.org/w/api.php?action=wbsearchentities&search=<Имя>&language=en&type=item&limit=3&format=json` — для Спинозы, Локка, Беркли, Брентано, Гуссерля (первичные догадки QID оказались чужими сущностями).
2. **Проверка сущностей:** `https://www.wikidata.org/w/api.php?action=wbgetentities&ids=...&props=labels|descriptions&languages=ru|en&format=json` — метка, описание, тип.
3. **Портреты и годы:** `https://query.wikidata.org/sparql?format=json&query=...` — один запрос `VALUES ?item { ... }` с `OPTIONAL { ?item wdt:P569 ?birth }`, `OPTIONAL { ?item wdt:P570 ?death }`, `OPTIONAL { ?item wdt:P18 ?image }`; второй запрос — `?item wdt:P373 ?cat` для категорий Commons.
4. **Метаданные файлов:** `https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiextmetadatafilter=Artist|DateTimeOriginal|LicenseShortName|LicenseUrl|UsageTerms|Credit&titles=File:...` — до 20 файлов за запрос; поля `width`, `height`, `mime`, `descriptionurl` берутся из `imageinfo`, остальные — из `extmetadata`.
5. **Категории и альтернативы:** `list=categorymembers&cmtitle=Category:<...>&cmtype=file&cmlimit=20-40`; проверялись `Category:Immanuel Kant`, `Category:Ludwig Wittgenstein`, `Category:Bertrand Russell`, `Category:Georg Wilhelm Friedrich Hegel`, `Category:René Descartes`, `Category:Benedictus de Spinoza`, `Category:Franz Brentano`, `Category:George Berkeley`, а также `Category:Portraits of Georg Wilhelm Friedrich Hegel`, `Category:Portraits of Ludwig Wittgenstein`, `Category:Portraits of Bertrand Russell`, `Category:Portraits of René Descartes`; `Category:Portrait paintings of Immanuel Kant` и `Category:Portraits of Edmund Husserl` вернули пустой список.
6. Решение по допустимости — по `LicenseShortName` + наличию `descriptionurl`; причины отказов записаны словами в §2.

Ограничения проверки: правомерность лицензий в отдельных юрисдикциях и сторонние притязания (§6, п. 2) не оценивались; содержимое изображений визуально не просматривалось (файлы не скачивались), решения о «похожести/дублях» — по названиям, авторам и датам, а не по пикселям.
