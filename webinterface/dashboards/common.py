from decoRouter import Router as decoRouter
from starlette.responses import RedirectResponse

router = decoRouter()
@router.get("/")
async def index(request):
    return RedirectResponse(url="tests")