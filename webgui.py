import uvicorn
import base64
import binascii
import sys
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.responses import HTMLResponse
from starlette.responses import PlainTextResponse
from starlette.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates
from starlette.authentication import requires
from starlette.authentication import (
    AuthenticationBackend, AuthenticationError, SimpleUser, 
    UnauthenticatedUser, AuthCredentials
)
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.config import Config
from starlette.datastructures import URL, Secret

# App-specific includes
import common.helper as helper
import common.config as config


class ExtendedUser(SimpleUser):
    def __init__(self, username: str, is_admin: False) -> None:
        self.username = username
        self.admin_status = is_admin

    @property
    def is_admin(self) -> bool:
        return self.admin_status


class SessionAuthBackend(AuthenticationBackend):
    async def authenticate(self, request):

        username=request.session.get("user")
        if username==None:
            return

        credentials=["authenticated"]
        is_admin=False

        if request.session.get("is_admin", "False")=="Jawohl":
            credentials.append("admin")
            is_admin=True

        return AuthCredentials(credentials), ExtendedUser(username,is_admin)


webgui_config = Config("webgui.env")
SECRET_KEY = webgui_config('SECRET_KEY', cast=Secret, default="NONE")
WEBGUI_PORT = webgui_config('PORT', cast=int, default=8000)
WEBGUI_HOST = webgui_config('HOST', default='0.0.0.0')
templates = Jinja2Templates(directory='webgui/templates')

app = Starlette(debug=True)
app.mount('/static', StaticFiles(directory='webgui/statics'), name='static')
app.add_middleware(AuthenticationMiddleware, backend=SessionAuthBackend())
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


def get_user_information(request):
    return { "logged_in": request.user.is_authenticated, "user": request.user.display_name, "is_admin": request.user.is_admin }


@app.route('/logs')
@requires('authenticated', redirect='login')
async def logs(request):
    template = "generic.html"
    context = {"request": request}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/rules')
@requires('authenticated', redirect='login')
async def rules(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "rules.html"
    context = {"request": request, "rules": config.hermes["rules"]}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/rules/edit/{rule}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def rules_edit(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    rule=request.path_params["rule"]
    template = "rules_edit.html"
    context = {"request": request, "rules": config.hermes["rules"], "targets": config.hermes["targets"], "rule": rule}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/rules/edit/{rule}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_edit_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    rule=request.path_params["rule"]
    form = dict(await request.form())

    return JSONResponse(form)    


@app.route('/rules/delete/{rule}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_delete_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    rule=request.path_params["rule"]    
    print("User wants to delete rule ",rule)

    return RedirectResponse(url='/rules', status_code=303)   


@app.route('/targets')
@requires('authenticated', redirect='login')
async def targets(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "targets.html"
    context = {"request": request, "targets": config.hermes["targets"]}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/users')
@requires(['authenticated','admin'], redirect='homepage')
async def users(request):
    template = "generic.html"
    context = {"request": request}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/configuration')
@requires(['authenticated','admin'], redirect='homepage')
async def configuration(request):
    template = "generic.html"
    context = {"request": request}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/login')
async def login(request):
    request.session.clear()
    template = "login.html"
    context = {"request": request }
    return templates.TemplateResponse(template, context)


@app.route("/login", methods=["POST"])
async def login_post(request):
    form = dict(await request.form())
    if (form["password"]=="hermes"):
        request.session.update({"user": form["username"]})

        if form["username"]=="admin":
            request.session.update({"is_admin": "Jawohl"})

        return RedirectResponse(url='/', status_code=303)
    else:
        template = "login.html"
        context = {"request": request, "invalid_password": 1 }
        return templates.TemplateResponse(template, context)


@app.route('/logout')
async def logout(request):
    request.session.clear()
    return RedirectResponse(url='/login')


@app.route('/')
@requires('authenticated', redirect='login')
async def homepage(request):
    template = "index.html"
    context = {"request": request}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/error')
async def error(request):
    """
    An example error. Switch the `debug` setting to see either tracebacks or 500 pages.
    """
    raise RuntimeError("Oh no")


@app.exception_handler(404)
async def not_found(request, exc):
    """
    Return an HTTP 404 page.
    """
    template = "404.html"
    context = {"request": request}
    return templates.TemplateResponse(template, context, status_code=404)


@app.exception_handler(500)
async def server_error(request, exc):
    """
    Return an HTTP 500 page.
    """
    template = "500.html"
    context = {"request": request}
    return templates.TemplateResponse(template, context, status_code=500)


if __name__ == "__main__":
    try:
        config.read_config()
    except Exception as e: 
        print(e)
        print("Cannot start service. Going down.")
        print("")
        sys.exit(1)

    if (SECRET_KEY=='NONE'):
        print("ERROR: No secret key defined! Not starting service.")
        sys.exit(1)

    uvicorn.run(app, host=WEBGUI_HOST, port=WEBGUI_PORT)
