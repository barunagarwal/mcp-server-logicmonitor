# Description: Paged /alert/alerts responder for respx, shaped on the portal's paging.
# Description: Serves size/offset slices with an exact total or the portal's lower-bound total.

import httpx


def alert_pages(alerts: list[dict], lower_bound: bool = False):
    """Return a respx side effect that serves alerts by the request's size and offset.

    With lower_bound, a page that leaves rows behind reports -(offset + size + 1),
    the form a read-only probe of lmryanmatuszewski returned on 2026-10-22
    (accesslogs size 5 offset 10 gave -16, alerts size 3 offset 3 gave -7); a page
    that reaches the end reports the exact count (alerts size 1000 gave 248).
    Without it, every page reports the exact count.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        size = int(request.url.params.get("size", 50))
        offset = int(request.url.params.get("offset", 0))
        page = alerts[offset : offset + size]
        more = lower_bound and offset + size < len(alerts)
        total = -(offset + size + 1) if more else len(alerts)
        return httpx.Response(200, json={"items": page, "total": total})

    return respond
