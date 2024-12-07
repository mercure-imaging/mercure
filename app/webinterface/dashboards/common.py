from decoRouter import Router as decoRouter
from starlette.responses import RedirectResponse, JSONResponse

router = decoRouter()


@router.get("/")
async def index(request):
    return RedirectResponse(url="query")


class JSONErrorResponse(JSONResponse):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(content={"error": message}, status_code=status_code)
