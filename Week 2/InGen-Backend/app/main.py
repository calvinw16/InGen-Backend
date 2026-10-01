import uuid

from fastapi import FastAPI, Request

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.logging import configure_logging

# App is main backend application object
app = FastAPI(
    title="Aido Backend Service",
    version="0.1.0",
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
