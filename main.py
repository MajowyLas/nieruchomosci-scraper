#!/usr/bin/env python
"""Punkt wejscia aplikacji. Uruchom: python main.py [scrape|raport|wszystko]"""
import sys
from scraper.cli import main

if __name__ == "__main__":
    sys.exit(main())
