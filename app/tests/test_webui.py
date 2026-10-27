"""
test_webui.py
=============

Covers every route that renders a Jinja template.

Before this coverage existed the whole web UI could fail to render while the suite stayed green:
``test_webui.py`` only imported ``webgui``. The explicit list below is here because Starlette 1.x
requires the ``Request`` as the first argument of ``Jinja2Templates.TemplateResponse()``; the
pre-1.x ``TemplateResponse(name, {"request": request})`` form is only supported up to 0.47.x and
raises from 1.0 on. See ``test_template_response_uses_request_first_argument`` for the static
counterpart, which also covers the call sites that need live server state to reach over HTTP.
"""
import ast
import functools
import os
import pathlib
import warnings

import pytest
from starlette.testclient import TestClient

# imported exactly like tests/conftest.py does: ``import webgui`` would bind a *different* module
# object than the one the test_client fixture configures
from app import webgui
from webinterface.common import templates

APP_DIR = pathlib.Path(webgui.__file__).resolve().parent

# Routes that render a template with the state the test configuration provides:
# (method, path, expected status, the call site this renders)
TEMPLATE_ROUTES = [
    ("GET", "/", 200, "webgui.homepage"),
    ("GET", "/login", 200, "webgui.login"),
    ("GET", "/settings", 200, "webgui.settings_edit"),
    ("GET", "/configuration", 200, "webgui.configuration"),
    ("GET", "/configuration/edit", 200, "webgui.configuration_edit"),
    ("GET", "/queue/", 200, "webinterface.queue.show_queues"),
    ("GET", "/rules/", 200, "webinterface.rules.rules"),
    ("GET", "/targets/", 200, "webinterface.targets.show_targets"),
    ("GET", "/targets/edit/dummy", 200, "webinterface.targets.targets_edit"),
    ("POST", "/targets/test/dummy", 200, "webinterface.targets.targets_test_post"),
    ("GET", "/modules/", 200, "webinterface.modules.show_modules"),
    ("GET", "/modules/edit/test_module", 200, "webinterface.modules.edit_module"),
    ("GET", "/users/", 200, "webinterface.users.show_users"),
    ("GET", "/users/edit/admin", 200, "webinterface.users.users_edit"),
    ("GET", "/tools/tasks", 200, "webinterface.dashboards.simple.tasks"),
    ("GET", "/tools/tests", 200, "webinterface.dashboards.simple.tests"),
    ("GET", "/tools/upload", 200, "webinterface.dashboards.dicomweb.upload"),
    ("GET", "/tools/query", 200, "webinterface.dashboards.query_routes.query"),
]


def test_webgui_no_syntax_errors():
    """Checks if webgui.py can be started."""
    assert webgui


@pytest.mark.parametrize("method, path, status, call_site", TEMPLATE_ROUTES,
                         ids=[r[3] for r in TEMPLATE_ROUTES])
def test_template_routes_render_html(test_client, method, path, status, call_site):
    """Every templated page renders HTML rather than raising."""
    response = test_client.request(method, path)
    assert response.status_code == status, f"{call_site} returned {response.status_code}"
    assert response.headers["content-type"].startswith("text/html"), f"{call_site} did not render HTML"


def test_rule_edit_page_renders(test_client, mercure_config):
    """webinterface.rules.rules_edit renders once the rule exists in the configuration."""
    mercure_config({"rules": {"test_rule": {"rule": "True", "target": "dummy", "action": "route"}}})
    response = test_client.get("/rules/edit/test_rule")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path, reason", [
    ("/logs", "No services configured"),
    ("/logs/bookkeeper", "Service does not exist"),
    ("/rules/edit/nonexistent_rule", "Rule does not exist anymore"),
])
def test_template_routes_short_circuit_without_state(test_client, path, reason):
    """Pages that need live state say so instead of rendering a broken template.

    Their ``TemplateResponse()`` calls (``webgui.show_first_log``, ``webgui.show_log``,
    ``webinterface.rules.rules_edit``) are checked statically by
    ``test_template_response_uses_request_first_argument``, as are the two that need a live Redis
    queue to reach at all (``webinterface.dashboards.query_routes.get_job_info`` renders a job
    fragment, and ``webinterface.dashboards.query_routes.query`` only renders the fragment for an
    existing job).
    """
    response = test_client.get(path)
    assert response.status_code == 200, f"{path} unexpectedly returned {response.status_code}"
    assert response.headers["content-type"].startswith("text/plain")
    assert reason in response.text


def test_not_found_page_is_rendered(test_client):
    """The 404 handler renders 404.html (it calls templates.TemplateResponse too)."""
    response = test_client.get("/this_page_does_not_exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


def test_server_error_page_is_rendered(test_client, monkeypatch):
    """The 500 handler renders 500.html for GET requests.

    Two Starlette details make this test look convoluted:
    * handlers registered under ``500``/``Exception`` are wired to ``ServerErrorMiddleware``, which
      only sees *non-HTTP* exceptions; an ``HTTPException(500)`` is answered by the default
      ``HTTPException`` handler instead;
    * ``ServerErrorMiddleware`` skips the handler entirely when the app runs with ``debug=True``,
      which is what the ``test_client`` fixture sets up.
    """
    real_get_template = templates.get_template

    def failing_get_template(name):
        # every page fails except the error page, which the handler still has to render
        if name != "500.html":
            raise RuntimeError("simulated failure while rendering")
        return real_get_template(name)

    monkeypatch.setattr(templates, "get_template", failing_get_template)
    monkeypatch.setattr(webgui, "DEBUG_MODE", False)
    monkeypatch.setattr(webgui, "SECRET_KEY", "asdfasdf")

    # a top-level route: pages under a mount (e.g. /tools/...) belong to a sub-application that
    # has no exception handlers of its own
    client = TestClient(webgui.create_app(), raise_server_exceptions=False)
    client.post("/login", data={"username": "admin", "password": "router"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False)

    response = client.get("/settings")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")


_EXCLUDED_DIRS = frozenset({"tests", "dicomweb_client"})


def _project_python_files(directory: pathlib.Path):
    """Yield the first-party ``*.py`` files under ``directory``, sorted.

    Walks with ``os.walk`` so that unwanted trees are *pruned* rather than listed and discarded:
    ``.venv`` holds ~5300 third-party files, and every ``app/tests`` test runs on the pyfakefs
    filesystem (the autouse ``mercure_config`` fixture asks for ``fs``), where a real-directory
    passthrough walk of that tree costs ~13s, against ~0.2s for the ~120 files that matter. It also
    kept old dependencies' SyntaxWarnings alive in the suite output.
    """
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(
            name for name in dirnames
            if not name.startswith(".") and name != "__pycache__" and name not in _EXCLUDED_DIRS
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield pathlib.Path(dirpath) / name


@functools.lru_cache(maxsize=None)
def _template_response_calls(directory: pathlib.Path):
    """Return ((file, node), ...) for every ``*.TemplateResponse(...)`` call under ``directory``.

    Cached: two tests scan the same tree, and parsing it is the whole cost of this check.
    """
    found = []
    for path in _project_python_files(directory):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "TemplateResponse":
                found.append((path, node))
    return tuple(found)


def test_all_template_response_call_sites_are_found():
    """Guards the static check itself against silently matching nothing."""
    calls = _template_response_calls(APP_DIR)
    assert len(calls) >= 24, f"expected the 24 known TemplateResponse call sites, found {len(calls)}"


def test_template_response_uses_request_first_argument():
    """No call site may use the pre-1.x ``TemplateResponse(name, {"request": request})`` order.

    Starlette 0.36-0.47 accept the old order with a DeprecationWarning; Starlette >= 1.0 removed
    it, at which point the template name lands in ``request`` and the context dict in ``name``.
    """
    offending = []
    for path, node in _template_response_calls(APP_DIR):
        if not node.args:
            offending.append(f"{path.relative_to(APP_DIR)}:{node.lineno} (no positional arguments)")
            continue
        first = node.args[0]
        request_first = isinstance(first, ast.Name) and "request" in first.id
        if not request_first:
            rendered = getattr(first, "id", None) or getattr(first, "value", None) or ast.dump(first)[:40]
            offending.append(f"{path.relative_to(APP_DIR)}:{node.lineno} (first argument is {rendered})")

    assert not offending, "TemplateResponse must be called as TemplateResponse(request, name, context):\n" \
        + "\n".join(offending)


def test_template_routes_emit_no_deprecation_warnings(test_client):
    """Rendering the covered pages must not raise Starlette deprecation warnings."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _, path, _, _ in TEMPLATE_ROUTES:
            test_client.get(path)

    starlette_deprecations = sorted(
        {f"{w.filename}:{w.lineno}: {w.message}" for w in caught
         if issubclass(w.category, DeprecationWarning) and "starlette" in str(w.filename)})
    assert not starlette_deprecations, "Starlette deprecation warnings while rendering:\n" \
        + "\n".join(starlette_deprecations)
