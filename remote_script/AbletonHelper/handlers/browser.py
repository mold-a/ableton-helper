"""Browser commands: status / rescan / search (index) and list / load (live walk)."""

from ..browser_index import (LIST_CATEGORIES, category_root, get_children, make_entry,
                             public_entry, resolve_path)
from ..dispatcher import (BAD_REQUEST, NOT_FOUND, UNSUPPORTED, CommandError, get_bool,
                          get_int, get_list, get_str)
from ..livecompat import devices_summary, device_list, safe_get, same
from .common import resolve_track, select_track


def _index(ctx):
    if ctx.browser_index is None:
        raise CommandError(UNSUPPORTED, "Browser index is not available")
    return ctx.browser_index


def _categories_param(params):
    cats = get_list(params, "categories", None)
    if cats is None:
        return None
    for c in cats:
        if not isinstance(c, str):
            raise CommandError(BAD_REQUEST, "'categories' must be an array of strings")
    return cats


def browser_status(ctx, params):
    return _index(ctx).status()


def browser_rescan(ctx, params):
    cats = _categories_param(params)
    _index(ctx).rescan(cats)
    return {"started": True}


def browser_search(ctx, params):
    index = _index(ctx)
    query = get_str(params, "query", allow_empty=True)
    cats = _categories_param(params)
    loadable_only = get_bool(params, "loadable_only", True)
    limit = get_int(params, "limit", 25, minimum=1, maximum=500)
    items = index.search(query, cats, loadable_only, limit)
    return {"items": items, "index_complete": index.complete}


def _browser(ctx):
    browser = safe_get(ctx.application, "browser", None)
    if browser is None:
        raise CommandError(UNSUPPORTED, "Browser API is not available")
    return browser


def browser_list(ctx, params):
    browser = _browser(ctx)
    path = get_str(params, "path", "", allow_empty=True).strip("/")
    if not path:
        items = []
        for category in LIST_CATEGORIES:
            root = category_root(browser, category)
            if root is None:
                continue
            uri = safe_get(root, "uri", None) if not isinstance(root, (list, tuple)) else None
            items.append({"name": category, "uri": str(uri) if uri else category, "path": category,
                          "category": category, "is_loadable": False, "is_device": False,
                          "is_folder": True})
        return {"items": items}
    node, category, parent = resolve_path(browser, path)
    if node is None:
        raise CommandError(NOT_FOUND, "Browser path not found: %s" % path)
    return {"items": [public_entry(make_entry(child, parent, category)) for child in get_children(node)]}


def _same_devices(a, b):
    return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))


def load_browser_item(ctx, params):
    _ti, track = resolve_track(ctx, params)
    uri = get_str(params, "uri", None)
    path = get_str(params, "path", None)
    if not uri and not path:
        raise CommandError(BAD_REQUEST, "Either 'uri' or 'path' is required")
    browser = _browser(ctx)
    if not hasattr(browser, "load_item"):
        raise CommandError(UNSUPPORTED, "browser.load_item is not available")
    item = None
    name = None
    if ctx.browser_index is not None:
        entry = ctx.browser_index.find(uri, path)
        if entry is not None:
            item, name = entry["ref"], entry["name"]
    if item is None and path:
        node, _cat, _canonical = resolve_path(browser, path)
        if node is not None and not isinstance(node, (list, tuple)):
            item, name = node, str(safe_get(node, "name", ""))
    if item is None:
        raise CommandError(NOT_FOUND, "Browser item not found: %s" % (uri or path))
    if not safe_get(item, "is_loadable", False):
        raise CommandError(BAD_REQUEST, "Browser item '%s' is not loadable" % name)
    before = device_list(track)
    select_track(ctx, track)
    browser.load_item(item)
    after = device_list(track)   # read AFTER the mutation
    result = {"loaded": True, "name": name, "devices": devices_summary(track)}
    if _same_devices(before, after):
        # Either the load is asynchronous in this Live version, or it replaced a device with
        # an identical one. Report what we currently see and let the client re-read if needed.
        result["pending"] = True
    return result


COMMANDS = {
    "browser_status": browser_status,
    "browser_rescan": browser_rescan,
    "browser_search": browser_search,
    "browser_list": browser_list,
    "load_browser_item": load_browser_item,
}
