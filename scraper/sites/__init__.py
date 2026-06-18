"""Adaptery poszczegolnych portali nieruchomosci."""
from .base import BaseScraper
from .olx import OlxScraper
from .gratka import GratkaScraper
from .nieruchomosci_online import NieruchomosciOnlineScraper
from .tarnowiak import TarnowiakScraper
from .otodom import OtodomScraper

# Rejestr: nazwa z config.yaml -> klasa adaptera
SCRAPERS: dict[str, type[BaseScraper]] = {
    "olx": OlxScraper,
    "otodom": OtodomScraper,
    "gratka": GratkaScraper,
    "nieruchomosci-online": NieruchomosciOnlineScraper,
    "tarnowiak": TarnowiakScraper,
}
