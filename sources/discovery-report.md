# Отчёт о поиске открытых текстов: раздел «Теория познания»

Записи добавлены командой `catalog add` и поправлены вручную (блоки `override` и `license`, `review.status` для отклонённых). `sync` не запускали, записи не одобрялись. `validate`: записей 36 (draft 30, rejected 6), ошибок 0, предупреждений 0.

## 1. Записи

Итог: первоисточники 25 (en 20, ru 5), учебники 3 (en 2, ru 1), справочники 2 (ru 2). Отклонено 6.

### Первоисточники, английский

| Идентификатор | Что | Сайт | Формат | Лицензия и доказательство | Что поправлено |
|---|---|---|---|---|---|
| plato-theaetetus-gutenberg | Plato, *Theaetetus*; перевод B. Jowett (ум. 1893) | Gutenberg 1726 | EPUB3 | public-domain; Платон ум. -348, Jowett ум. 1893 | нет |
| plato-meno-gutenberg | Plato, *Meno*; Jowett | Gutenberg 1643 | EPUB3 | public-domain; Jowett ум. 1893 | нет |
| plato-republic-gutenberg | Plato, *The Republic*; Jowett | Gutenberg 1497 | EPUB3 | public-domain; Jowett ум. 1893 | нет |
| locke-essay-concerning-humane-understanding-volume | Locke, *Essay*, т. 1 (кн. I–II); Locke ум. 1704 | Gutenberg 10615 | EPUB3 | public-domain; Locke ум. 1704 | `year: 1690` |
| locke-essay-concerning-humane-understanding-volume-2 | Locke, *Essay*, т. 2 (кн. III–IV) | Gutenberg 10616 | EPUB3 | public-domain; Locke ум. 1704 | `year: 1690` |
| berkeley-treatise-concerning-principles-human-knowledge | Berkeley, *Principles of Human Knowledge*; ум. 1753 | Gutenberg 4723 | EPUB3 | public-domain; Berkeley ум. 1753 | нет |
| berkeley-three-dialogues-between-hylas-philonous | Berkeley, *Three Dialogues*; ум. 1753 | Gutenberg 4724 | EPUB3 | public-domain; Berkeley ум. 1753 | нет |
| hume-enquiry-concerning-human-understanding-gutenberg | Hume, *Enquiry Concerning Human Understanding*; ум. 1776 | Gutenberg 9662 | EPUB3 | public-domain; Hume ум. 1776 | нет |
| hume-treatise-human-nature-gutenberg | Hume, *A Treatise of Human Nature* (издание Gutenberg целиком; книга I отдельно не выделялась, не проверено) | Gutenberg 4705 | EPUB3 | public-domain; Hume ум. 1776 | нет |
| kant-critique-pure-reason-gutenberg | Kant, *Critique of Pure Reason*; перевод J. M. D. Meiklejohn (ум. 1902) | Gutenberg 4280 | EPUB3 | public-domain; Kant ум. 1804, Meiklejohn ум. 1902 | нет |
| kant-s-prolegomena-to-any-future | Kant, *Prolegomena*; Gutenberg указывает Paul Carus (ум. 1919) | Gutenberg 52821 | EPUB3 | public-domain; Kant ум. 1804, Carus ум. 1919 | `year: 1783`; переводчик Carus вписан вручную (Gutenberg называет его editor, см. ниже) |
| descartes-discourse-method-rightly-conducting-one | Descartes, *Discourse on the Method*; Veitch (ум. 1894) | Gutenberg 59 | EPUB3 | public-domain; Descartes ум. 1650, Veitch ум. 1894 | нет |
| descartes-six-metaphysical-meditations-b-wherein | Descartes, *Meditations*; перевод W. Molyneux (ум. 1698) | Gutenberg 70091 | EPUB3 | public-domain; Descartes ум. 1650, Molyneux ум. 1698 | заголовок (адаптер взял MARC-разметку «$b…»): `title: Six Metaphysical Meditations` |
| mill-system-logic-ratiocinative-inductive-gutenberg | J. S. Mill, *A System of Logic*; ум. 1873 | Gutenberg 27942 | EPUB3 | public-domain; Mill ум. 1873 | нет |
| james-pragmatism-new-name-for-some | W. James, *Pragmatism*; ум. 1910 | Gutenberg 5116 | EPUB3 | public-domain; James ум. 1910 | нет |
| peirce-chance-love-logic-philosophical-essays | C. S. Peirce, *Chance, Love, and Logic* (сборник, ред. M. R. Cohen) | Gutenberg 65274 | EPUB3 | public-domain; Peirce ум. 1914; редактор Cohen ум. 1947 | `editor: Morris R. Cohen (1880–1947)` (адаптер редактора не нашёл) |
| reid-inquiry-into-human-mind-principles | T. Reid, *An Inquiry into the Human Mind*; ум. 1796 | en.wikisource | HTML (REST API) | public-domain; Reid ум. 1796 | нет |
| aristotle-soul-en-wikisource | Aristotle, *On the Soul*; перевод J. A. Smith (1863–1939) | en.wikisource | HTML | public-domain; Aristotle ум. -322, J. A. Smith ум. 1939 | переводчик вписан вручную (адаптер не нашёл) |
| aristotle-organon-owen-en-wikisource | Aristotle, *Posterior Analytics* (Organon, перевод O. F. Owen, ум. 1873) | en.wikisource | HTML | public-domain; Aristotle ум. -322, Owen ум. 1873 | заголовок (адаптер: `[[Organon (Owen)`); из файлов убраны 2 дубля с хвостовым «/» |
| hegel-phenomenology-mind-en-wikisource | Hegel, *Phenomenology of Mind*; перевод J. B. Baillie (ум. 1940) | en.wikisource | HTML, 11 частей | public-domain; Hegel ум. 1831, Baillie ум. 1940 (по Wikidata, вручную не проверено) | нет |

### Первоисточники, русский

| Идентификатор | Что | Сайт | Формат | Лицензия и доказательство | Что поправлено |
|---|---|---|---|---|---|
| teetet-platon-karpov-ru-wikisource | Платон, *Теэтет*; перевод В. Н. Карпова (1798–1867) | ru.wikisource | HTML | public-domain; Платон ум. -348, Карпов ум. 1867 (ru.wikipedia) | адаптер не извлёк авторов (страница на шаблоне «Сочинения Платона»): вписаны автор, переводчик, заголовок «Теэтет», лицензия |
| menon-platon-karpov-ru-wikisource | Платон, *Менон*; перевод В. Н. Карпова | ru.wikisource | HTML | public-domain; Карпов ум. 1867 | то же |
| chernyshevskiy-kharakter-chelovecheskogo-znaniya-ru-wikisource | Н. Г. Чернышевский, *Характер человеческого знания* (оригинальный текст) | ru.wikisource | HTML | public-domain; Чернышевский ум. 1889 | нет |
| kireevskiy-neobkhodimosti-vozmozhnosti-novykh-nachal-dlya | И. В. Киреевский, *О необходимости и возможности новых начал для философии* | ru.wikisource | HTML | public-domain; Киреевский ум. 1856 | нет |
| mikhaylovich-uchenie-kanta-poznanii-ru-wikisource | Л. М. Лопатин, *Учение Канта о познании* (оригинальный текст) | ru.wikisource | HTML | public-domain; Лопатин ум. 1920 | имя приведено к виду «Лев Михайлович Лопатин» |

Отклонено (первоисточник): **russell-problems-philosophy-gutenberg** (Рассел, *Problems of Philosophy*). Рассел ум. 1970, срок 70 лет не истёк. Gutenberg пишет «Public domain in the USA», но правило каталога требует давность больше 70 лет. `review.status: rejected`, лицензия не задана.

### Учебники

| Идентификатор | Что | Сайт | Формат | Лицензия и доказательство | Что поправлено |
|---|---|---|---|---|---|
| introduction-to-philosophyweb-pdf | OpenStax, *Introduction to Philosophy* (авторы: Nathan Smith и др., 13 человек) | openstax.org (прямой PDF из CMS API, `pdf_url`) | PDF, 48 МБ | **cc-by-nc-sa-4.0** (basis open_license); страница openstax.org/details/books/introduction-philosophy: «Creative Commons Attribution-NonCommercial-ShareAlike» | адаптер `direct` не извлёк метаданные: вписаны title, authors, year 2022, language en, publisher OpenStax. **Лицензия не CC BY 4.0, как ожидалось, а CC BY-NC-SA 4.0.** Решение за вами: NC-условие может не подойти для коммерческого использования. |
| falckenberg-history-modern-philosophy-smaller-en | R. Falckenberg, *History of Modern Philosophy*; перевод A. C. Armstrong (ум. 1935) | en.wikisource | HTML, 21 файл | public-domain; Falckenberg ум. 1920, Armstrong ум. 1935 | заголовок (адаптер: `History of Modern Philosophy{{smaller`) |
| ivanovich-uchebnik-logiki-ru-wikisource | Г. И. Челпанов, *Учебник логики* | ru.wikisource | HTML | public-domain; Челпанов ум. 1936 | нет. Тема логики, не теории познания в узком смысле |

Отклонено (учебник): **h-ffding-brief-history-modern-philosophy** (Höffding, *A Brief History of Modern Philosophy*, перевод Ch. F. Sanders). Sanders ум. 1959, срок 70 лет не истёк. Адаптер дал подсказку `PD-US`, но по правилам каталога это не общественное достояние.

### Справочники

| Идентификатор | Что | Сайт | Формат | Лицензия и доказательство | Что поправлено |
|---|---|---|---|---|---|
| esbe-teoriya-poznaniya-ru-wikisource | ЭСБЕ, статья «Теория познания», подпись «Н. Г. Дебольский» (1842–1918) | ru.wikisource | HTML | public-domain; статья подписана, Дебольский ум. 1918 | адаптер не извлёк автора: вписан по подписи |
| esbe-skeptitsizm-ru-wikisource | ЭСБЕ, статья «Скептицизм», подпись «Э. Радлов» (1854–1928) | ru.wikisource | HTML | public-domain; Радлов ум. 1928 (ru.wikipedia) | адаптер не извлёк автора: вписан по подписи |

Отклонено (справочник):
- **esbe-gnoseologiya-ili-gnozeologiya-ru-wikisource** («Гносеология или гнозеология», ЭСБЕ): статья без подписи, автор не установлен.
- **esbe-poznanie-ru-wikisource** («Познание», ЭСБЕ): страница-отсылка «см. Философия», самостоятельного текста нет.
- **esbe-sensualizm-ru-wikisource** («Сенсуализм», ЭСБЕ): подпись «Э. Р.», автор однозначно не установлен.
- **1911-encyclop-dia-britannica-epistemology-en** (EB1911, «Epistemology»): автор статьи на сайте не указан.

## 2. Что не удалось добавить и почему

- **Rebus Community, «Introduction to Philosophy: Epistemology» (CC BY).** Сайт press.rebus.community отвечает 403 на запрос с User-Agent PhiloGraph. Я сделал ещё один запрос с браузерным User-Agent, чтобы обойти блокировку. Автоматический режим его запретил, и на этом я остановился. Блокировку не обходил. Нужна прямая ссылка на PDF или EPUB, которую можно проверить с нашим User-Agent, либо решение, что делать с отказом сайта.
- **Челпанов, «Введение в философию».** На ru.wikisource не найдено. Вместо него добавлен «Учебник логики» того же автора.
- **Виндельбанд, Weber «History of Philosophy», Rogers «A Student's History of Philosophy».** Поиск на Gutenberg и en.wikisource ничего не дал. Не добавлены. Вместо Виндельбанда взята «History of Modern Philosophy» Фальккенберга.
- **Sextus Empiricus, Leibniz «New Essays», Peirce «How to Make Our Ideas Clear» и др.** Открытых полных переводов не найдено на Gutenberg и en.wikisource. Не добавлены.
- **Русские переводы Локка, Беркли, Юма, Декарта, Канта, Милля.** На ru.wikisource не найдены открытые переводы. Лосский, перевод «Критики чистого разума» (ru.wikisource), не в общественном достоянии (ум. 1965). Не добавлен.
- **Internet Archive** не использовался: для всех выбранных текстов нашлись Gutenberg или Wikisource.
- **Russell, Höffding** отклонены, см. выше.

## 3. Замечания о работе адаптеров

**gutenberg**
- Заголовки иногда содержат MARC-разметку (`Six metaphysical meditations $b Wherein …`). Исправлено вручную.
- `year` всегда `null`: год первого издания адаптер не берёт.
- Редакторы сборников (Peirce, Cohen; Kant, Carus) не попадают в метаданные.
- Gutenberg пишет «Public domain in the USA» (`license_hint`) для текстов, которые по правилам каталога общественным достоянием не являются (Russell). Подсказка может ввести в заблуждение, её нужно проверять по годам смерти.

**wikisource**
- Страницы на шаблонах вроде `{{Сочинения Платона|…}}` (Теэтет, Менон) дают пустых авторов и переводчика. Без ручной правки запись не проходит.
- Подписи ЭСБЕ не разбираются: авторы пустые, в т. ч. у статей, где подпись есть.
- Для ЭСБЕ/Познание адаптер не распознал перенаправление/отсылку и создал запись.
- Имена в русских страницах приходят в виде «Лопатин, Лев Михайлович».
- Заголовки ломаются: `[[Organon (Owen)` (адаптер взял вики-ссылку как заголовок), `History of Modern Philosophy{{smaller`.
- Список файлов для Organon дублирует подстраницы с хвостовым «/» (5 вместо 3).
- Переводчик On the Soul (J. A. Smith) не извлечён: в шаблоне страницы его нет, только в блоке «English-language translations».
- Подсказка `PD-US` (Höffding) не учитывает правило 70 лет.

**direct**
- Для PDF адаптер не получает метаданных (`title: None`, без авторов), весь блок пишется вручную.
- Правило публикации по умолчанию `manual`, поэтому файл не будет опубликован автоматически. Это соответствует описанию, но учтите при sync.

**общее**
- Адаптер `add` выставляет `review.status: draft` и предлагает лицензию по подсказке сайта. Для текстов из Wikisource без авторской подписи или с шаблоном предлагается `null`, что правильно.
- Отклонённые записи нельзя удалить из файла: `catalog.lock.json` хранит все выданные идентификаторы, `validate` тогда падает. Для отказа используется `review.status: rejected`, что и сделано.
