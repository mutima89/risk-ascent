"""Launcher used by PyInstaller and for running from source: python RiskAscent.py"""

import sys

from riskascent.app import main

if __name__ == "__main__":
    sys.exit(main())
