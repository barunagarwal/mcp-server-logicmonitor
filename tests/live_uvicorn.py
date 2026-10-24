# Description: Live-socket helper for HTTP transport tests that need real uvicorn behavior.
# Description: Records the uvicorn servers a test builds and serves one with a bounded startup.

import asyncio
import contextlib
import time


def free_port(host: str) -> int:
    """Ask the OS for a port that is free on ``host`` right now."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def live_uvicorn(monkeypatch):
    """Return a runner for real-socket tests: ``async with live(coro) as port``.

    Records every uvicorn.Server built after the call, runs ``coro`` (a
    ``server.serve()`` call, or ``create_http_server()``, which builds its own
    server) as a task, waits for the first recorded server to start, and yields
    its bound port. On exit it asks that server to stop and awaits the task. A
    task that ends before startup re-raises its error instead of leaving the wait
    to spin, and startup is bounded at 10 seconds. ``live.servers`` lists the
    recorded servers, so a test can assert that none was built.
    """
    import uvicorn

    servers: list[uvicorn.Server] = []

    class RecordingServer(uvicorn.Server):
        def __init__(self, config: uvicorn.Config) -> None:
            super().__init__(config)
            servers.append(self)

    monkeypatch.setattr(uvicorn, "Server", RecordingServer)

    @contextlib.asynccontextmanager
    async def serve(coro):
        task = asyncio.ensure_future(coro)
        try:
            deadline = time.monotonic() + 10
            while not (servers and servers[0].started):
                if task.done():
                    task.result()
                    raise RuntimeError("server task ended before startup")
                if time.monotonic() > deadline:
                    raise TimeoutError("server did not start within 10 seconds")
                await asyncio.sleep(0.01)
            yield servers[0].servers[0].sockets[0].getsockname()[1]
        finally:
            if servers:
                servers[0].should_exit = True
            else:
                task.cancel()
            await asyncio.wait({task})
        if task.exception() is not None:
            raise task.exception()

    serve.servers = servers
    return serve
