"""
test_bookkeeper.py
==================
"""
import multiprocessing
import time

import requests
from bookkeeping import bookkeeper
from testing_common import bookkeeper_port, mercure_config  # noqa: F401

# def run_server(app, port):
#     b.uvicorn.run(app, host="localhost", port=port)


def test_bookkeeper_starts(fs, bookkeeper_port, mercure_config):   # noqa: F811
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
