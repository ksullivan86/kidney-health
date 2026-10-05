"""Runtime settings read from environment variables.

Environment variables (see ARCHITECTURE.md):

* ``DATA_DIR``      directory holding ``kidney.db``. Default ``./data-local`` when
                    running outside a container and ``/data`` inside one.
* ``USDA_API_KEY``  optional FoodData Central key enabling the USDA proxy endpoints.
* ``APP_PASSWORD``  optional; when set every route requires HTTP Basic auth.
* ``FOODS_JSON``    path of the builtin food database. Default ``<repo>/data/foods.json``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOODS_JSON = REPO_ROOT / "data" / "foods.json"
DB_FILENAME = "kidney.db"

# Files that exist only inside an OCI container (podman / docker).
_CONTAINER_MARKERS = ("/run/.containerenv", "/.dockerenv")


def in_container() -> bool:
    return any(os.path.exists(p) for p in _CONTAINER_MARKERS)


def default_data_dir() -> Path:
    return Path("/data") if in_container() else Path("./data-local")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    usda_api_key: str | None = None
    app_password: str | None = None
    foods_json: Path = DEFAULT_FOODS_JSON

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    def ensure_data_dir(self) -> Path:
        """Create ``DATA_DIR`` (and parents) if it does not exist yet."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from ``env`` (defaults to ``os.environ``).

    Empty strings are treated as unset so that ``APP_PASSWORD=`` in a compose file
    does not accidentally enable authentication with an empty password.
    """
    env = os.environ if env is None else env

    data_dir = Path(env.get("DATA_DIR") or default_data_dir())
    usda_api_key = (env.get("USDA_API_KEY") or "").strip() or None
    app_password = env.get("APP_PASSWORD") or None
    foods_json = Path(env.get("FOODS_JSON") or DEFAULT_FOODS_JSON)

    return Settings(
        data_dir=data_dir,
        usda_api_key=usda_api_key,
        app_password=app_password,
        foods_json=foods_json,
    )
