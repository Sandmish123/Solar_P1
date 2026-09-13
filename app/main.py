from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from contextlib import asynccontextmanager

from app.config import get_settings
from app.api.routes import projects, geospatial

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize things here if needed
    os.makedirs("./temp_pdfs", exist_ok=True)
    yield
    # Clean up temp files
    try:
        if os.path.exists("./temp_pdfs"):
            for f in os.listdir("./temp_pdfs"):
                os.remove(os.path.join("./temp_pdfs", f))
    except Exception:
        pass


app = FastAPI(
    title="Solar Energy Report API",
    description="Backend for the Side Hustler Solar Proposal App",
    version="1.0.0",
    lifespan=lifespan
)

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "environment": settings.APP_ENV}


# Include Routers
app.include_router(projects.router, prefix="/api")
app.include_router(geospatial.router, prefix="/api")

# Mount frontend static files
app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
app.mount("/assets", StaticFiles(directory="frontend/assets"), name="assets")
app.mount("/js", StaticFiles(directory="frontend/js"), name="js")

@app.get("/")
def serve_frontend_index():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return {"message": "Frontend not found"}
