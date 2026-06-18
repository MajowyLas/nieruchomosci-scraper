"""Wczytywanie i walidacja pliku config.yaml."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class Config:
    miasto: str = "tarnow"
    typy: list[str] = field(default_factory=lambda: ["mieszkanie", "dom"])
    transakcja: str = "sprzedaz"
    cena_min: Optional[int] = None
    cena_max: Optional[int] = None
    powierzchnia_min: Optional[float] = None
    powierzchnia_max: Optional[float] = None
    pokoje_min: Optional[int] = None
    pokoje_max: Optional[int] = None
    portale: list[str] = field(default_factory=lambda: ["olx", "gratka", "nieruchomosci-online", "tarnowiak"])
    max_stron: int = 3
    opoznienie: float = 1.5
    okazja_prog_procent: float = 85.0


def load_config(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Nie znaleziono pliku konfiguracji: {p}. "
            "Skopiuj config.yaml z repozytorium i dostosuj parametry."
        )
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = Config(
        miasto=str(raw.get("miasto", "tarnow")).strip().lower(),
        typy=[str(t).strip().lower() for t in (raw.get("typy") or ["mieszkanie", "dom"])],
        transakcja=str(raw.get("transakcja", "sprzedaz")).strip().lower(),
        cena_min=_as_int(raw.get("cena_min")),
        cena_max=_as_int(raw.get("cena_max")),
        powierzchnia_min=_as_float(raw.get("powierzchnia_min")),
        powierzchnia_max=_as_float(raw.get("powierzchnia_max")),
        pokoje_min=_as_int(raw.get("pokoje_min")),
        pokoje_max=_as_int(raw.get("pokoje_max")),
        portale=[str(s).strip().lower() for s in (raw.get("portale") or [])],
        max_stron=int(raw.get("max_stron", 3)),
        opoznienie=float(raw.get("opoznienie", 1.5)),
        okazja_prog_procent=float(raw.get("okazja_prog_procent", 85)),
    )

    # walidacja
    valid_types = {"mieszkanie", "dom"}
    bad = [t for t in cfg.typy if t not in valid_types]
    if bad:
        raise ValueError(f"Nieznane typy nieruchomosci w config.yaml: {bad}. Dozwolone: {valid_types}")
    if not cfg.portale:
        raise ValueError("Lista 'portale' w config.yaml jest pusta - nie ma czego scrapowac.")
    if cfg.max_stron < 1:
        cfg.max_stron = 1
    return cfg


def _as_int(value) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
