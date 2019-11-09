
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory='webinterface/templates')


def get_user_information(request):
    """Returns dictionary of values that should always be passed to the templates when the user is logged in."""
    return { "logged_in": request.user.is_authenticated, "user": request.user.display_name, "is_admin": request.user.is_admin }

