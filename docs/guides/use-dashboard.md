# Run the dashboard

The dashboard launches existing application use cases and displays their stored artifacts. It does
not implement a second physics, economics, or statistics layer.

## Run locally

```powershell
python -m pip install -e ".[dashboard]"
python -m solarclean.dashboard
```

Open `http://127.0.0.1:8050`. Run the command from the repository root so `configs/` and
`outputs/` resolve correctly. Select `offline_fixture_full_year.yaml` for a network-free study.

## Configure a deployment

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `SOLARCLEAN_DASHBOARD_HOST` | `127.0.0.1` | Bind address |
| `SOLARCLEAN_DASHBOARD_PORT` | `8050` | Listen port |
| `SOLARCLEAN_ROOT` | Current directory | Base path for configs and outputs |
| `SOLARCLEAN_CONFIGS_DIR` | `<root>/configs` | Explicit configuration directory |
| `SOLARCLEAN_OUTPUTS_DIR` | `<root>/outputs` | Explicit output directory |
| `SOLARCLEAN_DASHBOARD_TOKEN` | Unset | HTTP Basic password for every request |

Example behind a reverse proxy:

```bash
export SOLARCLEAN_ROOT=/srv/solarclean
export SOLARCLEAN_DASHBOARD_HOST=0.0.0.0
export SOLARCLEAN_DASHBOARD_PORT=8050
export SOLARCLEAN_DASHBOARD_TOKEN='replace-with-a-secret'
python -m solarclean.dashboard
```

Treat the token as an administrator credential. An authenticated user can run studies, edit the
dashboard's default configuration, and delete run packages. Do not expose an unauthenticated
instance outside localhost.

## Operating limits

- Use one application process and one worker. Job state is in-process; the dashboard runs one
  analysis at a time and keeps later submissions in a FIFO queue.
- Serve at the domain root or a dedicated subdomain; mounting below a URL path is unsupported.
- NASA POWER studies need outbound HTTPS unless the requested weather is cached.
- Finished run packages remain under `outputs/`. Download important packages before deleting them.
- A displayed recommendation comes from stored artifacts and is omitted when backend
  reconciliation withholds it.

The resolved configuration and every displayed study artifact remain downloadable from the result
page.
