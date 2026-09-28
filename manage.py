#!/usr/bin/env python
"""Administración local de BIG PARTY."""
import os
import sys

from dotenv import load_dotenv


def main():
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parent / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
