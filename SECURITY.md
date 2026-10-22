# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | Yes                |
| < 2.0   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Use [private vulnerability reporting](https://github.com/ryanmat/mcp-server-logicmonitor/security/advisories/new),
   which is enabled on this repository and keeps the report private until a fix
   ships. The "Report a vulnerability" button on the Security tab does the same.
3. Include a detailed description of the vulnerability and steps to reproduce

You can expect:
- Acknowledgment within 48 hours
- Regular updates on the fix progress
- Credit in the security advisory (unless you prefer anonymity)

## Security Considerations

### Credential Handling
- Bearer tokens are passed via environment variables only
- Never commit tokens to version control
- Use `.env` files locally (included in `.gitignore`)

### Inbound HTTP Exposure
- The HTTP transport drives the full tool surface with the server's LogicMonitor
  credentials. Anyone who can reach the port can use them.
- Set `LM_HTTP_AUTH_TOKEN` whenever the port is reachable beyond localhost:
  `/mcp` and `/api/v1/*` then require `Authorization: Bearer <token>` and
  return 401 otherwise. A bind outside `127.0.0.1`, `::1` and `localhost`
  refuses to start without it unless `LM_HTTP_ALLOW_UNAUTHENTICATED=true`
  accepts the exposure; the default `LM_HTTP_HOST` is `0.0.0.0`.
- Request bodies on `/mcp` and `/api/v1/*` must be `application/json` (415
  otherwise), and every route except `/healthz` and `/readyz` answers only the
  loopback names, a non-wildcard `LM_HTTP_HOST` and `LM_HTTP_ALLOWED_HOSTS` in
  `Host` (400 otherwise). Together they block cross-site form posts and DNS
  rebinding from a page in the operator's browser.
- `/`, `/health`, `/healthz`, and `/readyz` stay unauthenticated so container
  healthchecks and orchestrator probes keep working. Their responses carry
  component status, never LogicMonitor data. None of them calls the
  LogicMonitor API for an unauthenticated caller: `/readyz` never does, and
  with `LM_HEALTH_CHECK_CONNECTIVITY=true` (off by default) `/health` adds the
  API connectivity check only when the request carries `LM_HTTP_AUTH_TOKEN`,
  or when no token is configured and `/mcp` is open anyway. Earlier releases
  pinged the API on every `/readyz` request when that flag was on, letting an
  anonymous caller consume your portal's API quota; that is fixed (issue #56).
- Pair the token with TLS (the Caddy profile in `deploy/`, or `LM_HTTP_SSL_*`)
  so it is not sent in cleartext.
- The stdio transport is unaffected: it has no listening socket.

### Write Operations
- Write operations are disabled by default
- Enable only when needed: `LM_ENABLE_WRITE_OPERATIONS=true`
- Review permissions granted to your LogicMonitor API token

### Container Security
- Docker image runs as non-root user
- Minimal base image (python:slim)
- No sensitive data persisted in container

### Best Practices
- Use dedicated API tokens with minimal required permissions
- Rotate tokens regularly
- Monitor LogicMonitor audit logs for unexpected API activity
