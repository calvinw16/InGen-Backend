import uuid
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.logging import configure_logging
from app.models.perception import ErrorResponse

# App is main backend application object
app = FastAPI(
    title="Aido Backend Service",
    version="0.1.0",
)


def get_request_id(request: Request) -> str:
    return getattr(
        request.state,
        "request_id",
        str(uuid4()),
    )


@app.exception_handler(HTTPException)
async def http_error_handler(
    request: Request,
    exc: HTTPException,
):
    detail = exc.detail

    if isinstance(detail, dict):
        code = str(detail.get("code", "HTTP_ERROR"))
        message = str(detail.get("message", "Request failed"))
    else:
        code = "HTTP_ERROR"
        message = str(detail)

    error = ErrorResponse(
        code=code,
        message=message,
        request_id=get_request_id(request),
        details={},
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error.model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
):
    error = ErrorResponse(
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        request_id=get_request_id(request),
        details={
            "error_count": len(exc.errors()),
        },
    )

    return JSONResponse(
        status_code=422,
        content=error.model_dump(mode="json"),
    )


app.include_router(health_router)
app.include_router(v1_router)


# Ensure every HTTP request has a request ID
# Run for every HTTP request
# Eventually attach id to log info aswell
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get(
        "X-Request-ID",
        str(uuid.uuid4()),
    )

    request.state.request_id = request_id

    # Call correct route
    response = await call_next(request)

    # Adds request ID to the appropriate header
    response.headers["X-Request-ID"] = request_id

    return response


@app.get("/")
def root():
    return {"message": "InGen backend is running"}


# Configure the internal logging format
configure_logging()
