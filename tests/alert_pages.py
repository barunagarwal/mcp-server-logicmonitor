# Description: Paged /alert/alerts responders for respx, shaped on the portal's paging.
# Description: Serves size/offset slices, and routes cleared:true reads to their own list.

import httpx


def _page(alerts: list[dict], request: httpx.Request, lower_bound: bool) -> httpx.Response:
    """Serve the slice of alerts the request's size and offset name."""
    size = int(request.url.params.get("size", 50))
    offset = int(request.url.params.get("offset", 0))
    page = alerts[offset : offset + size]
    more = lower_bound and offset + size < len(alerts)
    total = -(offset + size + 1) if more else len(alerts)
    return httpx.Response(200, json={"items": page, "total": total})


def alert_pages(alerts: list[dict], lower_bound: bool = False):
    """Return a respx side effect that serves alerts by the request's size and offset.

    With lower_bound, a page that leaves rows behind reports -(offset + size + 1),
    the form a read-only probe of lmryanmatuszewski returned on 2026-10-22
    (accesslogs size 5 offset 10 gave -16, alerts size 3 offset 3 gave -7); a page
    that reaches the end reports the exact count (alerts size 1000 gave 248).
    Without it, every page reports the exact count.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        return _page(alerts, request, lower_bound)

    return respond


def alert_lists(
    active: list[dict],
    cleared: list[dict] | None = None,
    lower_bound: bool = False,
    cleared_lower_bound: bool | None = None,
):
    """Return a respx side effect that serves active and cleared alerts as two lists.

    Both alert lists return active alerts only unless the filter carries
    cleared:true (probe of lmryanmatuszewski, 2026-10-22), so a request whose
    filter holds that clause reads the cleared list and any other the active
    one, each paged as alert_pages pages. cleared_lower_bound defaults to
    lower_bound.
    """
    cleared = cleared or []
    if cleared_lower_bound is None:
        cleared_lower_bound = lower_bound

    def respond(request: httpx.Request) -> httpx.Response:
        clauses = request.url.params.get("filter", "").split(",")
        if "cleared:true" in clauses:
            return _page(cleared, request, cleared_lower_bound)
        return _page(active, request, lower_bound)

    return respond
