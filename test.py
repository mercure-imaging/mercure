from starlette.testclient import TestClient
from webgui import *
import time
import common.config as config

services.read_services()
config.read_config()
users.read_users()

def run_test() -> None:
    config.read_config()
    config.mercure.study_complete_trigger = 2
    config.mercure.series_complete_trigger = 1
    config.save_config()

    client = TestClient(app)
    startup()
    form_data = {
        "username": "admin",
        "password": "router"
    }
    response = client.post(  
        "/login", 
        data=form_data,
        headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
    )
    assert response.status_code == 200

    response = client.post(
        "/self_test",
        data={"type":"process"},
        headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
    )
    assert response.status_code == 200
    test_id = response.json()["test_id"]
    print("Test id",test_id)

    response = client.get(
        "/api/get-tests",
        headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
    )
    assert response.status_code == 200
    tests = response.json()
    assert tests[0]["id"] == test_id
    assert tests[0]["status"] in ("begin","success")

    for i in range(200):
        time.sleep(0.1)
        response = client.get(
            "/api/get-tests",
            headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
        )
        tests = response.json()
        if tests[0]["status"] == "success": 
            logger.info("Success!")
            return
        if tests[0]["status"] == "failed": 
            logger.error("Test failed.")
            break
    else:
        logger.error("Test timed out.")
    logger.info("Processing logs:")
    response = client.get(
        "/logs/processor",
        headers={ 'Content-Type': 'application/x-www-form-urlencoded', 'accept':'application/json'}
    )
    print("\n".join(response.json()["logs"].split("\n")[-100:]))
    logger.error("Test failed.")

if __name__ == "__main__":
    run_test()
# response = client.get(
#     "/api/get_tests",
#     data={type:"process"},
#     headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
# )

