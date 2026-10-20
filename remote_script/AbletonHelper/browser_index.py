"""Incremental index of Live's browser. Pure logic: takes an `application` object.

The walk is a generator; step() advances it for a bounded amount of time so that
Live's main thread never freezes. Everything here runs on the main thread.
"""

import time
import traceback

from .livecompat import safe_get

CATEGORY_ORDER = (
    "user_library", "instruments", "sounds", "drums", "audio_effects", "midi_effects",
    "packs", "samples", "clips", "plugins", "max_for_live", "user_folders",
)
LIST_CATEGORIES = CATEGORY_ORDER + ("current_project",)
MAX_DEPTH = 8
MAX_ITEMS = 60000
PUBLIC_KEYS = ("name", "uri", "path", "category", "is_loadable", "is_device", "is_folder")


def get_children(node):
    """Children of a BrowserItem (or items of a plain list), never raising."""
    if isinstance(node, (list, tuple)):
        return list(node)
    try:
        return list(node.children)
    except Exception:
        return []


def category_root(browser, category):
    """The browser attribute for a category (BrowserItem, or list for user_folders); None if missing."""
    root = safe_get(browser, category, None)
    if root is None:
        return None
    if not hasattr(root, "children") and not isinstance(root, (list, tuple)):
        try:
            root = list(root)
        except Exception:
            return None
    return root


def make_entry(item, parent_path, category):
    name = str(safe_get(item, "name", "") or "")
    path = parent_path + "/" + name
    uri = safe_get(item, "uri", None)
    uri = str(uri) if uri else path
    is_folder = safe_get(item, "is_folder", None)
    if is_folder is None:
        is_folder = bool(get_children(item))
    return {
        "name": name,
        "uri": uri,
        "path": path,
        "category": category,
        "is_loadable": bool(safe_get(item, "is_loadable", False)),
        "is_device": bool(safe_get(item, "is_device", False)),
        "is_folder": bool(is_folder),
        "ref": item,
        "_lpath": path.lower(),
        "_lname": name.lower(),
    }


def public_entry(entry):
    return dict((k, entry[k]) for k in PUBLIC_KEYS)


def find_child(children, name):
    """Child by name: exact, then case-insensitive."""
    for child in children:
        if str(safe_get(child, "name", "")) == name:
            return child
    lowered = name.lower()
    for child in children:
        if str(safe_get(child, "name", "")).lower() == lowered:
            return child
    return None


def resolve_path(browser, path):
    """Walk the live browser along 'category/a/b'. Returns (node, category, canonical_path).

    node is a BrowserItem or, for the category root of user_folders, a list.
    Returns (None, None, None) when nothing matches. canonical_path uses the real item names.
    """
    segments = [s for s in str(path).strip("/").split("/") if s]
    if not segments:
        return None, None, None
    category = segments[0].lower()
    if category not in LIST_CATEGORIES:
        return None, None, None
    node = category_root(browser, category)
    if node is None:
        return None, None, None
    canonical = category
    for segment in segments[1:]:
        child = find_child(get_children(node), segment)
        if child is None:
            return None, None, None
        node = child
        canonical += "/" + str(safe_get(child, "name", ""))
    return node, category, canonical


class BrowserIndex(object):
    def __init__(self, application, log=None, clock=None, max_depth=MAX_DEPTH, max_items=MAX_ITEMS):
        self._app = application
        self._log = log
        self._clock = clock or time.monotonic
        self.max_depth = max_depth
        self.max_items = max_items
        self._entries = []
        self._by_uri = {}
        self._by_path = {}
        self._gen = None
        self._start_at = 0.0
        self._complete = False
        self._truncated = False

    def log(self, message):
        if self._log is not None:
            try:
                self._log(message)
            except Exception:
                pass

    # ------------------------------------------------------------ control
    def start(self, delay=0.0):
        """(Re)build the whole index, beginning `delay` seconds from now."""
        self.rescan(None, delay)

    def rescan(self, categories=None, delay=0.0):
        if categories is None:
            cats = list(CATEGORY_ORDER)
            self._entries = []
            self._truncated = False
        else:
            wanted = set(categories)
            cats = [c for c in CATEGORY_ORDER if c in wanted]
            self._entries = [e for e in self._entries if e["category"] not in wanted]
        self._rebuild_maps()
        self._complete = False
        self._start_at = self._clock() + delay
        self._gen = self._walk(cats)

    def _rebuild_maps(self):
        self._by_uri = {}
        self._by_path = {}
        for entry in self._entries:
            self._by_uri.setdefault(entry["uri"], entry)
            self._by_path.setdefault(entry["path"], entry)

    def step(self, budget=0.02, max_items=2000):
        """Advance the walk for at most `budget` seconds. Returns items processed."""
        if self._gen is None or self._clock() < self._start_at:
            return 0
        started = self._clock()
        done = 0
        try:
            while done < max_items:
                next(self._gen)
                done += 1
                if done % 20 == 0 and self._clock() - started >= budget:
                    break
        except StopIteration:
            self._gen = None
            self._complete = True
        except Exception:
            self.log("Browser index walk failed: %s" % traceback.format_exc())
            self._gen = None
            self._complete = True
        return done

    def status(self):
        return {
            "indexed": len(self._entries),
            "complete": self._complete,
            "scanning": self._gen is not None,
            "truncated": self._truncated,
        }

    @property
    def complete(self):
        return self._complete

    # ------------------------------------------------------------ walk
    def _walk(self, categories):
        browser = safe_get(self._app, "browser", None)
        if browser is None:
            return
        for category in categories:
            try:
                root = category_root(browser, category)
                if root is None:
                    continue
                top = get_children(root)
                stack = [(iter(top), category, 1)]
                while stack:
                    iterator, prefix, depth = stack[-1]
                    try:
                        item = next(iterator)
                    except StopIteration:
                        stack.pop()
                        continue
                    entry = make_entry(item, prefix, category)
                    self._entries.append(entry)
                    self._by_uri.setdefault(entry["uri"], entry)
                    self._by_path.setdefault(entry["path"], entry)
                    if len(self._entries) >= self.max_items:
                        self._truncated = True
                        return
                    yield
                    if depth < self.max_depth:
                        children = get_children(item)
                        if children:
                            stack.append((iter(children), entry["path"], depth + 1))
            except Exception:
                self.log("Browser category %s failed: %s" % (category, traceback.format_exc()))

    # ------------------------------------------------------------ queries
    def find(self, uri=None, path=None):
        if uri and uri in self._by_uri:
            return self._by_uri[uri]
        if path and path in self._by_path:
            return self._by_path[path]
        return None

    def find_device(self, name, categories):
        lowered = name.lower()
        for entry in self._entries:
            if entry["is_device"] and entry["_lname"] == lowered and entry["category"] in categories:
                return entry
        return None

    def search(self, query, categories=None, loadable_only=True, limit=25):
        words = [w for w in str(query).lower().split() if w]
        hits = []
        for entry in self._entries:
            if categories and entry["category"] not in categories:
                continue
            if loadable_only and not entry["is_loadable"]:
                continue
            lpath = entry["_lpath"]
            ok = True
            for w in words:
                if w not in lpath:
                    ok = False
                    break
            if not ok:
                continue
            name_hits = sum(1 for w in words if w in entry["_lname"])
            hits.append((-name_hits, len(entry["path"]), entry))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [public_entry(h[2]) for h in hits[:limit]]
