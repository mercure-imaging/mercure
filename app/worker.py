"""Wrapper for rq worker that loads systemd credentials before starting."""
import sys
from common.credentials import load_credentials
load_credentials()
from rq.cli import main
main()
