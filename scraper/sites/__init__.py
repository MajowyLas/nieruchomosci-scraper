"""Adaptery poszczegolnych portali nieruchomosci."""
from .base import BaseScraper
from .olx import OlxScraper
from .gratka import GratkaScraper
from .nieruchomosci_online import NieruchomosciOnlineScraper
from .tarnowiak import TarnowiakScraper

# Rejestr: nazwa z config.yaml -> klasa adaptera
SCRAPERS: dict[str, type[BaseScraper]] = {
    "olx": OlxScraper,
    "gratka": GratkaScraper,
    "nieruchomosci-online": NieruchomosciOnlineScraper,
    "tarnowiak": TarnowiakScraper,
}
