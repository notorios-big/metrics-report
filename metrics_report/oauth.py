from __future__ import annotations

import argparse
from pathlib import Path


def _upsert_env_var(*, env_path: Path, key: str, value: str, force: bool) -> None:
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    raw = env_path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=False)

    out: list[str] = []
    found = False
    updated = False
    for line in lines:
        if not line.startswith(f"{key}="):
            out.append(line)
            continue

        found = True
        current = line.split("=", 1)[1]
        if current and not force:
            out.append(line)
            continue

        out.append(f"{key}={value}")
        updated = True

    if not found:
        out.append(f"{key}={value}")
        updated = True

    if updated:
        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _google_ads_refresh_token(
    *, client_secret_path: str, open_browser: bool, port: int
) -> str:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: google-auth-oauthlib. "
            "Install it with: `.venv/bin/pip install -r requirements.txt`"
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_path,
        scopes=["https://www.googleapis.com/auth/adwords"],
    )
    creds = flow.run_local_server(
        port=port,
        open_browser=open_browser,
        access_type="offline",
        prompt="consent",
    )
    token = getattr(creds, "refresh_token", None)
    if not token:
        raise RuntimeError(
            "Google did not return a refresh_token. "
            "Try again with a fresh consent (prompt=consent) and ensure the OAuth client is a 'Desktop app'."
        )
    return str(token)


def run_oauth_command(args: argparse.Namespace) -> None:
    if args.oauth_command != "google-ads":
        raise SystemExit(f"Unknown oauth command: {args.oauth_command}")

    refresh_token = _google_ads_refresh_token(
        client_secret_path=args.client_secret,
        open_browser=not args.no_browser,
        port=int(args.port),
    )

    if args.stdout:
        print(refresh_token)

    env_path = Path(args.env_file)
    _upsert_env_var(
        env_path=env_path,
        key="GOOGLE_ADS_OAUTH_REFRESH_TOKEN",
        value=refresh_token,
        force=bool(args.force),
    )

    if not args.stdout:
        print(f"Wrote GOOGLE_ADS_OAUTH_REFRESH_TOKEN to {env_path}")
