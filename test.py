import logging
from starlette.testclient import TestClient
from webgui import *
import time
import common.config as config

services.read_services()
config.read_config()
users.read_users()

import textwrap

def pretty_print_table(data, headers=None, max_width=35):
    if not data:
        print("No data to display")
        return

    # Determine if data is a list of dicts or a list of lists
    is_dict_data = isinstance(data[0], dict)

    # If headers are not provided, use the keys of the first dictionary in data
    # or generate column numbers for list data
    if headers is None:
        if is_dict_data:
            headers = list(data[0].keys())
        else:
            headers = [f"Column {i+1}" for i in range(len(data[0]))]

    # Calculate column widths
    col_widths = [len(str(header)) for header in headers]
    for row in data:
        for i, header in enumerate(headers):
            if is_dict_data:
                value = str(row.get(header, ""))
            else:
                value = str(row[i]) if i < len(row) else ""
            col_widths[i] = max(col_widths[i], len(value))

    # Limit column width to max_width
    col_widths = [min(width, max_width) for width in col_widths]

    # Print headers
    header_row = " | ".join(f"{header:<{col_widths[i]}}" for i, header in enumerate(headers))
    print(header_row)
    print("-" * len(header_row))

    # Print data rows
    for row in data:
        row_data = []
        for i, header in enumerate(headers):
            if is_dict_data:
                item = str(row.get(header, ""))
            else:
                item = str(row[i]) if i < len(row) else ""
            if len(item) > col_widths[i]:
                item = textwrap.fill(item, width=col_widths[i])
            row_data.append(item)
        
        # Split multiline cells into separate lines
        row_lines = [cell.split('\n') for cell in row_data]
        max_lines = max(len(lines) for lines in row_lines)
        
        for line_num in range(max_lines):
            line = " | ".join(f"{lines[line_num] if line_num < len(lines) else '':<{col_widths[i]}}"
                              for i, lines in enumerate(row_lines))
            print(line)
        
        # if max_lines > 1:
        #     print("-" * len(header_row))

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
    task_id = tests[0]["task_id"]
    try:
        logger = logging.getLogger('_client')
        logger.setLevel(logging.WARNING)
        for i in range(200):
            time.sleep(0.1)
            response = client.get(
                "/api/get-tests",
                headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
            )
            tests = response.json()
            task_id = tests[0]["task_id"]
            if tests[0]["status"] == "success": 
                logger.info("Success!")
                return
            if tests[0]["status"] == "failed": 
                logger.error("Test failed.")
                break
        else:
            logger.error("Test timed out.")
    finally:
        response = client.get(
            "/api/get-task-events?task_id="+task_id,
        )
        lines = response.json()
        pretty_print_table(lines, ['sender','event', 'info','target'])
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

