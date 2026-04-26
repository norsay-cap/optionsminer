"""Central configuration. Loaded once at import time and shared across the app."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPTIONSMINER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    db_filename: str = Field(default="optionsminer.db")

    tickers: list[str] = Field(default_factory=lambda: ["SPY", "^SPX"])

    risk_free_rate: float = Field(default=0.045, description="Annualised, decimal. SOFR proxy.")
    div_yield_spy: float = Field(default=0.013)
    div_yield_spx: float = Field(default=0.013)

    disk_cap_gb: float = Field(
        default=150.0, description="Hard cap on data dir size before auto-prune."
    )
    disk_warn_pct: float = Field(default=0.80, description="Warn at this fraction of cap.")

    snapshot_max_dte: int = Field(
        default=180, description="Skip expiries beyond this many days to keep DB lean."
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    def div_yield_for(self, ticker: str) -> float:
        t = ticker.upper().lstrip("^")
        if t == "SPY":
            return self.div_yield_spy
        return self.div_yield_spx


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
