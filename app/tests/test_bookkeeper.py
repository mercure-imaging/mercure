"""
test_bookkeeper.py
==================
"""
import multiprocessing
import time
from pathlib import Path

import requests
import testing_common
from bookkeeping import bookkeeper
from testing_common import bookkeeper_port, mercure_config

# def run_server(app, port):
#     b.uvicorn.run(app, host="localhost", port=port)

def test_bookkeeper_starts(fs, bookkeeper_port, mercure_config):
    """ Checks if bookkeeper.py can be started. """
    bookkeeper_process = multiprocessing.Process(target=bookkeeper.main)
    bookkeeper_process.start()
    # Wait for the server to start
    time.sleep(2)
    response = requests.get(f"http://127.0.0.1:{bookkeeper_port}/test")
    assert response.status_code == 200
    assert response.text == '{"ok":""}'
    # Shutdown the server
    print("Shutting down the server...")
    bookkeeper_process.terminate()
    bookkeeper_process.join()
