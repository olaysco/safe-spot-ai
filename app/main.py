import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from app.database import connect


def create_app(database_url=None, worker=True):
    engine, factory = connect(database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title='Safe Spot', lifespan=lifespan)
    app.state.db = factory

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'service': 'Safe Spot'}

    return app


app = create_app()
