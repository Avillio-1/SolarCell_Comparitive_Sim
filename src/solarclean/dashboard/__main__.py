import os

import uvicorn


def resolve_bind() -> tuple[str, int]:
    """Host/port from the environment so the app is not localhost-only.

    Defaults stay safe for a workstation (127.0.0.1:8050). For a web
    deployment set SOLARCLEAN_DASHBOARD_HOST=0.0.0.0 (behind a reverse proxy)
    and SOLARCLEAN_DASHBOARD_PORT as needed — see docs/dashboard_user_guide.md.
    """
    host = os.environ.get("SOLARCLEAN_DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    raw_port = os.environ.get("SOLARCLEAN_DASHBOARD_PORT", "8050").strip() or "8050"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit(f"SOLARCLEAN_DASHBOARD_PORT must be an integer, got {raw_port!r}") from exc
    return host, port


def main() -> None:
    # Reload is off on purpose: a reload mid-run would kill an in-flight
    # Monte Carlo job. Configs and outputs resolve from the working directory
    # unless SOLARCLEAN_ROOT / SOLARCLEAN_CONFIGS_DIR / SOLARCLEAN_OUTPUTS_DIR
    # pin them explicitly (recommended for deployments).
    host, port = resolve_bind()
    uvicorn.run("solarclean.dashboard.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
