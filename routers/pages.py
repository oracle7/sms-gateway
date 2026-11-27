from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from config import settings
from services.auth import AuthContext, get_optional_auth
from version import APP_VERSION, BUILD_ID

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _base_context(auth: AuthContext) -> dict:
    return {
        "user": auth.user,
        "csrf_token": auth.session.csrf_token,
        "sms_did": settings.SMS_DID,
        "build_id": BUILD_ID,
        "app_version": APP_VERSION,
        "idle_timeout_seconds": settings.SESSION_IDLE_TIMEOUT_MINUTES * 60,
    }


def register_page_routes(app: FastAPI) -> None:
    @app.get("/login")
    async def login_page(request: Request, auth: AuthContext = Depends(get_optional_auth)):
        if auth:
            return RedirectResponse(url="/", status_code=302)
        reason = request.query_params.get("reason", "")
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "reason": reason,
                "app_version": APP_VERSION,
                "build_id": BUILD_ID,
            },
        )

    @app.get("/")
    async def index_page(request: Request, auth: AuthContext = Depends(get_optional_auth)):
        if not auth:
            return RedirectResponse(url="/login", status_code=302)
        ctx = _base_context(auth)
        ctx["active_page"] = "messages"
        return templates.TemplateResponse(request=request, name="index.html", context=ctx)

    @app.get("/contacts")
    async def contacts_page(request: Request, auth: AuthContext = Depends(get_optional_auth)):
        if not auth:
            return RedirectResponse(url="/login", status_code=302)
        ctx = _base_context(auth)
        ctx["active_page"] = "contacts"
        return templates.TemplateResponse(request=request, name="contacts.html", context=ctx)

    @app.get("/admin")
    async def admin_page(request: Request, auth: AuthContext = Depends(get_optional_auth)):
        if not auth:
            return RedirectResponse(url="/login", status_code=302)
        if auth.user.role != "admin":
            return RedirectResponse(url="/", status_code=302)
        ctx = _base_context(auth)
        ctx["active_page"] = "admin"
        return templates.TemplateResponse(request=request, name="admin.html", context=ctx)
