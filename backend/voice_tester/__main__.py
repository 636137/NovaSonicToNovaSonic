"""
Entry point for running voice_tester as a module.

Usage:
    python -m voice_tester test scenarios/census_survey.yaml
    python -m voice_tester.cli test scenarios/census_survey.yaml
"""
from voice_tester.cli import main
import sys

if __name__ == '__main__':
    sys.exit(main())
