"""Retired mobile staging entry point. Never accesses Flutter or stage files."""
import sys


RETIRED = (
    "Mobile staging is retired: the actual Flutter repository "
    "D:/CHGO-VibeCodeing/neorang_narang_app is now authoritative. "
    "Retained .mobile-stage files are stale and must not be applied. "
    "Stage preparation and --apply are refused; no target files were accessed."
)


def refuse():
    print(RETIRED, file=sys.stderr)
    raise SystemExit(2)


def prepare():
    refuse()


def apply():
    refuse()


def main():
    refuse()


if __name__ == '__main__':
    main()
