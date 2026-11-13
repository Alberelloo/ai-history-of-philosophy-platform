"""Адаптеры сайтов: по ссылке на страницу источника — метаданные, ссылки на файлы, лицензия.

Каждый адаптер знает один сайт. Годы смерти авторов берутся из данных сайта, а если их
нет — из Wikidata. Адаптер ничего не решает о лицензии: он даёт подсказку, решает запись
каталога (review).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlsplit

from lxml import etree

from philograph.library.catalog.fetcher import Fetcher, FetchError
from philograph.platform import events

LANGS = {
    "eng": "en", "rus": "ru", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr",
    "lat": "la", "ita": "it", "grc": "grc", "gre": "el", "spa": "es",
}  # fmt: skip

events.define(
    "library.catalog.author_not_found",
    "warning",
    "На странице источника не удалось определить автора",
    required=("page",),
)


@dataclass
class Harvest:
    metadata: dict[str, Any]
    files: list[dict[str, Any]]
    license_hint: str | None = None
    slug_hint: list[str] = field(default_factory=list)  # слова для идентификатора записи


class Adapter(Protocol):
    name: str
    version: int

    def matches(self, url: str) -> bool: ...

    def harvest(self, url: str, fetcher: Fetcher) -> Harvest: ...


# --- Wikidata -----------------------------------------------------------------------


def _year(claim_time: str | None) -> int | None:
    if not claim_time:
        return None
    m = re.match(r"([+-]\d+)-", claim_time)
    return int(m.group(1)) if m else None


def _norm(value: str | None) -> str:
    """Название для сравнения: только буквы и цифры, без регистра и пунктуации."""
    return re.sub(r"[^a-zа-яё0-9]+", "", (value or "").lower())


def _titles_match(a: str, b: str | None) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na and nb) and (na in nb or nb in na)


class Wikidata:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._cache: dict[str, dict[str, Any]] = {}

    def entity(self, qid: str) -> dict[str, Any]:
        if qid not in self._cache:
            data = self.fetcher.get(
                f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", api=True
            ).json()
            self._cache[qid] = data["entities"].get(qid) or next(iter(data["entities"].values()))
        return self._cache[qid]

    def claims(self, qid: str, prop: str) -> list[Any]:
        values = []
        for claim in self.entity(qid).get("claims", {}).get(prop, []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if value is not None:
                values.append(value)
        return values

    def label(self, qid: str, lang: str) -> str | None:
        labels = self.entity(qid).get("labels", {})
        for code in (lang, "en", "ru"):
            if code in labels:
                return labels[code]["value"]
        return None

    def death_year(self, qid: str) -> int | None:
        for value in self.claims(qid, "P570"):
            year = _year(value.get("time"))
            if year is not None:
                return year
        return None

    def person(self, qid: str, lang: str) -> dict[str, Any]:
        return {
            "name": self.label(qid, lang) or qid,
            "death_year": self.death_year(qid),
            "wikidata": qid,
        }

    def find_person(self, name: str, lang: str) -> dict[str, Any] | None:
        """Человек по имени: первый найденный, у кого в Wikidata есть дата смерти."""
        try:
            found = self.fetcher.get(
                "https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&format=json"
                f"&limit=5&language={lang}&search={quote(name)}",
                api=True,
            ).json()
        except FetchError:
            return None
        for item in found.get("search", []):
            qid = item["id"]
            humans = [v.get("id") for v in self.claims(qid, "P31")]
            if "Q5" in humans and self.death_year(qid) is not None:
                return {"name": name, "death_year": self.death_year(qid), "wikidata": qid}
        return None

    def earliest_year(self, qid: str, prop: str) -> int | None:
        """Самый ранний год среди значений свойства (например, P577 — дата публикации)."""
        years = [y for y in (_year(v.get("time")) for v in self.claims(qid, prop)) if y is not None]
        return min(years) if years else None

    def search_items(self, query: str, lang: str) -> list[str]:
        """QID по запросу wbsearchentities; пустой список при ошибке сети."""
        try:
            found = self.fetcher.get(
                "https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&format=json"
                f"&limit=10&language={lang}&search={quote(query)}",
                api=True,
            ).json()
        except FetchError:
            return []
        return [item["id"] for item in found.get("search", [])]

    def first_publication_year(self, title: str, author: str | None, lang: str) -> int | None:
        """Год первой публикации книги: ищем произведение по названию, берём P577 (ранний).

        Если по названию не нашлось, пробуем автора через ``find_person`` и его связанные
        произведения (P800). Сеть или разбор Wikidata не должны ронять добавление источника:
        тогда год остаётся ``None``.
        """
        try:
            for qid in self.search_items(title, lang):
                year = self.earliest_year(qid, "P577")
                if year is not None:
                    return year
            if author:
                person = self.find_person(author, lang)
                if person:
                    for work in self.claims(person["wikidata"], "P800"):
                        work_qid = work.get("id") if isinstance(work, dict) else work
                        if work_qid and _titles_match(title, self.label(work_qid, lang)):
                            year = self.earliest_year(work_qid, "P577")
                            if year is not None:
                                return year
        except Exception:  # сеть или неожиданный формат ответа: год остаётся None
            return None
        return None


# --- Project Gutenberg ----------------------------------------------------------------

NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dcterms": "http://purl.org/dc/terms/",
    "pgterms": "http://www.gutenberg.org/2009/pgterms/",
    "marcrel": "http://id.loc.gov/vocabulary/relators/",
}


def _pg_name(raw: str) -> str:
    """«Locke, John» → «John Locke»; годы и уточнения в скобках отбрасываются."""
    raw = re.sub(r"\s*\(.*?\)\s*", " ", raw)
    raw = re.sub(r",?\s*\d{3,4}\??\s*-\s*(\d{3,4})?\??\s*$", "", raw).strip(" ,")
    if "," in raw:
        last, first = (p.strip() for p in raw.split(",", 1))
        return f"{first} {last}".strip()
    return raw


def _rdf_year(ebook: Any) -> int | None:
    """Год из RDF Gutenberg: dcterms:issued/created — дата издания на сайте."""
    for tag in ("dcterms:issued", "dcterms:created"):
        raw = (ebook.findtext(tag, default="", namespaces=NS) or "").strip()
        match = re.search(r"\d{4}", raw)
        if match:
            return int(match.group(0))
    return None


class Gutenberg:
    name = "gutenberg"
    version = 1

    def matches(self, url: str) -> bool:
        return bool(re.match(r"https?://(www\.)?gutenberg\.org/(ebooks|cache/epub)/\d+", url))

    def harvest(self, url: str, fetcher: Fetcher) -> Harvest:
        book = re.search(r"/(?:ebooks|cache/epub)/(\d+)", url).group(1)
        rdf = etree.fromstring(fetcher.get(f"https://www.gutenberg.org/ebooks/{book}.rdf").data)
        ebook = rdf.find("pgterms:ebook", NS)
        title = " ".join((ebook.findtext("dcterms:title", default="", namespaces=NS)).split())

        def agents(path: str) -> list[dict[str, Any]]:
            people = []
            for agent in ebook.findall(f"{path}/pgterms:agent", NS):
                death = agent.findtext("pgterms:deathdate", namespaces=NS)
                people.append(
                    {
                        "name": _pg_name(agent.findtext("pgterms:name", default="", namespaces=NS)),
                        "death_year": int(death) if death and death.lstrip("-").isdigit() else None,
                        "wikidata": None,
                    }
                )
            return people

        authors = agents("dcterms:creator")
        translators = agents("marcrel:trl")
        language = ebook.findtext("dcterms:language/rdf:Description/rdf:value", namespaces=NS)
        lang = LANGS.get(language or "", language or "en")
        year = Wikidata(fetcher).first_publication_year(
            title, authors[0]["name"] if authors else None, lang
        )
        if year is None:
            # В RDF Gutenberg ``dcterms:issued`` — дата выкладки на сайт (2004), а не первое
            # издание (1781). Берём её только если первой публикации не нашлось: пустое поле
            # хуже приблизительного значения.
            year = _rdf_year(ebook)
        formats = {}
        for f in ebook.findall("dcterms:hasFormat/pgterms:file", NS):
            about = f.get(f"{{{NS['rdf']}}}about")
            formats[about] = f.findtext("dcterms:format/rdf:Description/rdf:value", namespaces=NS)
        chosen = None
        for suffix in (".epub3.images", ".epub.images", ".epub.noimages", ".txt.utf-8"):
            for about in formats:
                if about.endswith(f"/ebooks/{book}{suffix}"):
                    chosen = about
                    break
            if chosen:
                break
        if chosen is None:
            chosen = f"https://www.gutenberg.org/ebooks/{book}.epub3.images"
        ext = "txt" if chosen.endswith(".txt.utf-8") else "epub"
        return Harvest(
            metadata={
                "title": title,
                "authors": authors,
                "language": lang,
                "year": year,
                "translator": translators[0] if translators else None,
                "publisher": "Project Gutenberg",
            },
            files=[{"name": f"pg{book}.{ext}", "url": chosen, "clean": "gutenberg"}],
            license_hint=ebook.findtext("dcterms:rights", namespaces=NS),
            slug_hint=[*(a["name"].split()[-1] for a in authors[:1]), title, "gutenberg"],
        )


# --- Wikisource -----------------------------------------------------------------------

_TEMPLATE_FIELDS = {
    "author": ("АВТОР", "author"),
    "translator": ("ПЕРЕВОДЧИК", "translator"),
    "title": ("НАЗВАНИЕ", "title"),
    "year": ("ДАТАПУБЛИКАЦИИ", "ДАТАСОЗДАНИЯ", "year"),
}


def _template_value(wikitext: str, names: tuple[str, ...]) -> str | None:
    """Значение параметра шаблона с учётом вложенных ``[[…|…]]`` и ``{{…|…}}``."""
    for name in names:
        m = re.search(rf"\|\s*{re.escape(name)}\s*=", wikitext)
        if not m:
            continue
        i, depth, out = m.end(), 0, []
        while i < len(wikitext):
            pair = wikitext[i : i + 2]
            if pair in ("[[", "{{"):
                depth += 1
                out.append(pair)
                i += 2
                continue
            if pair in ("]]", "}}"):
                if depth == 0:
                    break  # конец самого шаблона
                depth -= 1
                out.append(pair)
                i += 2
                continue
            if depth == 0 and wikitext[i] in "|\n":
                break
            out.append(wikitext[i])
            i += 1
        value = "".join(out).strip()
        if value:
            return value
    return None


def _links(value: str) -> list[str]:
    """«[[Иммануил Кант]], [[Автор:Н. Лосский|Н. Лосский]]» → страницы авторов."""
    return [m.split("|")[0].strip() for m in re.findall(r"\[\[([^\]]+)\]\]", value)]


def _plain(value: str) -> str:
    value = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", value)
    # {{smaller|текст}} → текст, {{abbr|ИМ|полное}} → полное; шаблоны без параметров
    # убираются; разбор идёт изнутри наружу
    for _ in range(5):
        value = re.sub(r"\{\{[^{}|]*\|([^{}]*)\}\}", lambda m: m.group(1).split("|")[-1], value)
        value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"'{2,}", "", value)
    return " ".join(value.split())


AUTHOR_NS = {"ru": "Автор", "en": "Author", "de": "Autor", "fr": "Auteur", "la": "Scriptor"}

_SERVICE_WORDS = frozenset(
    {
        "и",
        "на",
        "в",
        "во",
        "с",
        "со",
        "по",
        "о",
        "об",
        "от",
        "до",
        "из",
        "за",
        "к",
        "ко",
        "у",
        "the",
        "of",
        "and",
        "de",
        "von",
        "van",
        "le",
        "la",
        "der",
        "die",
        "das",
        "a",
        "an",
        "or",
        "in",
        "on",
        "et",
    }
)
_CAPITALIZED = re.compile(r"[A-ZА-ЯЁ][a-zа-яё-]*")
_INITIALS = re.compile(r"[A-ZА-ЯЁ](?:\.[A-ZА-ЯЁ])*\.?")


def _looks_like_person(name: str) -> bool:
    """Похоже ли на имя человека: 2–3 слова с заглавной, без цифр и служебных слов."""
    words = name.split()
    if not 2 <= len(words) <= 3:
        return False
    for word in words:
        if any(ch.isdigit() for ch in word):
            return False
        if word.lower() in _SERVICE_WORDS:
            return False
        if not (_CAPITALIZED.fullmatch(word) or _INITIALS.fullmatch(word)):
            return False
    return True


def _bold_name(wikitext: str, page: str) -> str | None:
    """Имя из первой строки с жирным начертанием, если она похожа на имя человека."""
    match = re.search(r"'''([^'\n]+)'''", wikitext)
    if not match:
        return None
    name = _plain(match.group(1)).strip()
    name = re.sub(r"[.\s–——-]+$", "", name).strip()
    if not name or _norm(name) == _norm(page.split("/")[-1]):
        return None
    return name if _looks_like_person(name) else None


def _template_author(wikitext: str) -> str | None:
    """Подпись автора из подшаблона: «{{ЭСБЕ/Автор|Н. Г. Дебольский}}».

    В справочных статьях автора ставят в конце именно так: позиционным параметром
    подшаблона, а не ссылкой на страницу автора и не жирной строкой. Подпись бывает
    завёрнута в оформление — «{{right|{{ЭСБЕ/Автор|Э. Радлов}}.}}», поэтому берём только
    до первой закрывающей скобки и снимаем разметку.
    """
    match = re.search(r"\{\{\s*[^|}\n]*Автор\s*\|\s*([^|}\n]+)", wikitext)
    if not match:
        return None
    name = _plain(match.group(1))
    name = name.split("}}", 1)[0].split("|", 1)[0]
    return name.strip(" .;,") or None


def _author_links(wikitext: str, lang: str) -> list[str]:
    """Ссылки на страницы авторов: «[[Автор:Фамилия, Имя]]», «[[Author:...]]» и т. п."""
    prefixes = tuple(
        f"{ns}:" for ns in dict.fromkeys([AUTHOR_NS.get(lang, "Author"), "Автор", "Author"])
    )
    return [target for target in _links(wikitext) if target.startswith(prefixes)]


def _resolve_people(
    targets: list[str], *, api: str, lang: str, fetcher: Fetcher, wikidata: Wikidata
) -> list[dict[str, Any]]:
    """Цели («[[Автор:…]]» или имена) → люди с годами смерти и QID, если они есть."""
    result = []
    for target in targets:
        target = target.strip()
        if not target:
            continue
        name = _pg_name(target.split(":", 1)[-1])
        years = re.search(r"\((?:\d{3,4})\s*[-–—]\s*(\d{3,4})\)", target)
        person: dict[str, Any] = {
            "name": name,
            "death_year": int(years.group(1)) if years else None,
            "wikidata": None,
        }
        title = target if ":" in target else f"{AUTHOR_NS.get(lang, 'Author')}:{target}"
        pages = fetcher.get(
            f"{api}?action=query&prop=pageprops&redirects=1&format=json&formatversion=2"
            f"&titles={quote(title)}",
            api=True,
        ).json()["query"]["pages"]
        qid = (pages[0].get("pageprops") or {}).get("wikibase_item") if pages else None
        if qid:
            found = wikidata.person(qid, lang)
            person.update(
                wikidata=qid,
                death_year=found["death_year"] or person["death_year"],
                name=found["name"] if found["name"] != qid else name,
            )
        result.append(person)
    return result


class Wikisource:
    """Текст — HTML страницы и подстраниц через REST API Wikimedia, в порядке оглавления.

    ws-export (EPUB) закрыт для программ в robots.txt, поэтому не используется.
    """

    name = "wikisource"
    version = 3  # 3: «красные» ссылки записываются как неоцифрованные подстраницы

    @staticmethod
    def rest_url(host: str, page: str) -> str:
        return f"https://{host}/api/rest_v1/page/html/{quote(page.replace(' ', '_'), safe='')}"

    def files(self, host: str, page: str, fetcher: Fetcher) -> list[dict[str, Any]]:
        """Главная страница и подстраницы по ссылкам из неё, в порядке появления.

        «Красная» ссылка — подстраницы на сайте нет: она записывается с ``missing``, и в тексте
        на её месте будет глава-заглушка, а не пропуск.
        """
        main = self.rest_url(host, page)
        body = fetcher.get(main, api=True).data
        prefix = page.replace(" ", "_") + "/"
        subpages: dict[str, bool] = {}  # название → нет на сайте
        for href in re.findall(rb'href="\./([^"]+)"', body):
            title = unquote(re.split(rb"[#?]", href)[0].decode("utf-8")).rstrip("/")
            if title.startswith(prefix) and title not in subpages:
                subpages[title] = b"redlink=1" in href
        result = [{"name": page, "url": main, "clean": "wikisource", "api": True}]
        for title, missing in subpages.items():
            item = {
                "name": title.replace("_", " "),
                "url": self.rest_url(host, title),
                "clean": "wikisource",
                "api": True,
            }
            if missing:
                item["missing"] = True
            result.append(item)
        return result

    def matches(self, url: str) -> bool:
        return bool(re.match(r"https?://[a-z-]+\.wikisource\.org/wiki/", url))

    def harvest(self, url: str, fetcher: Fetcher) -> Harvest:
        parts = urlsplit(url)
        lang = parts.netloc.split(".")[0]
        page = unquote(parts.path.split("/wiki/", 1)[1]).replace("_", " ")
        api = f"https://{parts.netloc}/w/api.php"
        query = fetcher.get(
            f"{api}?action=query&prop=pageprops&redirects=1&format=json&formatversion=2"
            f"&titles={quote(page)}",
            api=True,
        ).json()
        info = query["query"]["pages"][0]
        if info.get("missing") or info.get("invalid"):
            raise ValueError(f"на {parts.netloc} нет страницы «{page}»")
        page = info.get("title", page)
        wikitext = fetcher.get(
            f"{api}?action=parse&prop=wikitext&format=json&formatversion=2&page={quote(page)}",
            api=True,
        ).json()["parse"]["wikitext"]
        wikidata = Wikidata(fetcher)

        def people(field_names: tuple[str, ...]) -> list[dict[str, Any]]:
            raw = _template_value(wikitext, field_names)
            if not raw:
                return []
            # «[[Иммануил Кант]]» или «David Hume (1711-1776)»: страница автора по ссылке или имени
            targets = _links(raw) or [n for n in re.split(r",| и | and ", _plain(raw)) if n.strip()]
            return _resolve_people(targets, api=api, lang=lang, fetcher=fetcher, wikidata=wikidata)

        def fallback_authors() -> list[dict[str, Any]]:
            """Авторы на страницах без шапки: подпись в подшаблоне, жирная строка, ссылка."""
            signed = _template_author(wikitext)
            if signed:
                return _resolve_people(
                    [signed], api=api, lang=lang, fetcher=fetcher, wikidata=wikidata
                )
            bold = _bold_name(wikitext, page)
            if bold:
                return _resolve_people(
                    [bold], api=api, lang=lang, fetcher=fetcher, wikidata=wikidata
                )
            return _resolve_people(
                _author_links(wikitext, lang),
                api=api,
                lang=lang,
                fetcher=fetcher,
                wikidata=wikidata,
            )

        authors = people(_TEMPLATE_FIELDS["author"])
        if not authors:
            authors = fallback_authors()
        if not authors:
            events.emit("library.catalog.author_not_found", page=page)
        translators = people(_TEMPLATE_FIELDS["translator"])
        title = _plain(_template_value(wikitext, _TEMPLATE_FIELDS["title"]) or "") or page
        year_raw = _template_value(wikitext, _TEMPLATE_FIELDS["year"]) or ""
        year = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", year_raw)
        hints = re.findall(r"\{\{\s*((?:PD|CC|Licence|Лицензия)[^|}]*)", wikitext)
        return Harvest(
            metadata={
                "title": title,
                "authors": authors,
                "language": lang,
                "year": int(year.group(1)) if year else None,
                "translator": translators[0] if translators else None,
                "publisher": f"{lang}.wikisource.org",
            },
            files=self.files(parts.netloc, page, fetcher),
            license_hint=", ".join(dict.fromkeys(h.strip() for h in hints)) or None,
            slug_hint=[*(a["name"].split()[-1] for a in authors[:1]), title, lang, "wikisource"],
        )


# --- Internet Archive -----------------------------------------------------------------


class ArchiveOrg:
    name = "archive_org"
    version = 1
    PREFERRED = ("EPUB", "Text PDF", "Additional Text PDF", "DjVuTXT")

    def matches(self, url: str) -> bool:
        return bool(re.match(r"https?://(www\.)?archive\.org/details/", url))

    def harvest(self, url: str, fetcher: Fetcher) -> Harvest:
        item = urlsplit(url).path.split("/details/", 1)[1].split("/")[0]
        data = fetcher.get(f"https://archive.org/metadata/{item}", api=True).json()
        meta = data.get("metadata", {})

        def as_list(value: Any) -> list[str]:
            return [value] if isinstance(value, str) else list(value or [])

        wikidata = Wikidata(fetcher)
        language = LANGS.get(
            as_list(meta.get("language"))[:1][0] if meta.get("language") else "", "en"
        )
        authors = []
        for creator in as_list(meta.get("creator")):
            name = _pg_name(creator)
            m = re.search(r"(\d{4})-(\d{4})", creator)
            person = {"name": name, "death_year": int(m.group(2)) if m else None, "wikidata": None}
            if person["death_year"] is None:
                found = wikidata.find_person(name, language)
                if found:
                    person.update(found, name=name)
            authors.append(person)
        chosen = None
        for fmt in self.PREFERRED:
            chosen = next((f for f in data.get("files", []) if f.get("format") == fmt), None)
            if chosen:
                break
        files = []
        if chosen:
            files.append(
                {
                    "name": chosen["name"],
                    "url": f"https://archive.org/download/{item}/{quote(chosen['name'])}",
                }
            )
        year = re.search(r"\d{4}", str(meta.get("date") or meta.get("year") or ""))
        title = " ".join(str(meta.get("title", item)).split())
        hint = meta.get("licenseurl") or meta.get("rights") or meta.get("possible-copyright-status")
        return Harvest(
            metadata={
                "title": title,
                "authors": authors,
                "language": language,
                "year": int(year.group(0)) if year else None,
                "translator": None,
                "publisher": as_list(meta.get("publisher"))[:1][0]
                if meta.get("publisher")
                else None,
            },
            files=files,
            license_hint=str(hint) if hint else None,
            slug_hint=[*(a["name"].split()[-1] for a in authors[:1]), title, "archive"],
        )


# --- Прямая ссылка ------------------------------------------------------------------


class Direct:
    name = "direct"
    version = 1

    def matches(self, url: str) -> bool:
        return True

    def harvest(self, url: str, fetcher: Fetcher) -> Harvest:
        name = unquote(urlsplit(url).path.rstrip("/").split("/")[-1]) or "file"
        return Harvest(metadata={}, files=[{"name": name, "url": url}], slug_hint=[name])


ADAPTERS: list[Adapter] = [Gutenberg(), Wikisource(), ArchiveOrg(), Direct()]


def adapter_for(url: str, name: str | None = None) -> Adapter:
    if name:
        return next(a for a in ADAPTERS if a.name == name)
    return next(a for a in ADAPTERS if a.matches(url))


# --- идентификатор и подсказка лицензии -----------------------------------------------

_LATIN = "a b v g d e e zh z i y k l m n o p r s t u f kh ts ch sh shch - y - e yu ya".split()  # noqa: SIM905
_TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", _LATIN, strict=True))


def slugify(words: list[str], limit: int = 6) -> str:
    text = " ".join(words).lower()
    text = "".join(_TRANSLIT.get(ch, ch) for ch in text).replace("-", "")
    tokens = [
        t
        for t in re.split(r"[^a-z0-9]+", text)
        if t and t not in {"the", "of", "a", "an", "and", "on", "o", "i", "v"}
    ]
    dedup = list(dict.fromkeys(tokens))
    return "-".join(dedup[:limit])[:100] or "source"


LICENSE_HINTS = (
    (r"creativecommons\.org/licenses/by-sa/4\.0|CC[- ]BY[- ]SA[- ]4\.0", "cc-by-sa-4.0"),
    (r"creativecommons\.org/licenses/by-sa/3\.0|CC[- ]BY[- ]SA[- ]3\.0", "cc-by-sa-3.0"),
    (r"creativecommons\.org/licenses/by-nc-sa/4\.0|CC[- ]BY[- ]NC[- ]SA", "cc-by-nc-sa-4.0"),
    (r"creativecommons\.org/licenses/by-nc/4\.0|CC[- ]BY[- ]NC[- ]4", "cc-by-nc-4.0"),
    (r"creativecommons\.org/licenses/by/4\.0|CC[- ]BY[- ]4\.0", "cc-by-4.0"),
)


def suggest_license(harvest: Harvest, year: int) -> dict[str, Any] | None:
    """Черновик лицензии по подсказке сайта; окончательно решает review записи."""
    hint = harvest.license_hint or ""
    for pattern, code in LICENSE_HINTS:
        if re.search(pattern, hint, re.I):
            return {"kind": code, "basis": "open_license", "evidence": f"сайт: {hint}"}
    if re.search(r"public domain|PD-|publicdomain|NOT_IN_COPYRIGHT", hint, re.I) or (
        harvest.metadata.get("publisher") or ""
    ).endswith("wikisource.org"):
        people = list(harvest.metadata.get("authors") or [])
        if harvest.metadata.get("translator"):
            people.append(harvest.metadata["translator"])
        deaths = [p.get("death_year") for p in people]
        if people and all(d is not None for d in deaths) and all(d + 70 < year for d in deaths):
            detail = "; ".join(f"{p['name']} ум. {p['death_year']}" for p in people)
            return {
                "kind": "public-domain",
                "basis": "public_domain",
                "evidence": f"сайт: {hint or 'Wikisource'}; {detail}",
            }
    return None
