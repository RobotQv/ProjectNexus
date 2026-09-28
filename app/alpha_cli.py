"""显式重建检索派生索引，不重解析正文，不变更审核记录或来源锚点。"""

import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db import begin_write, build_engine, session_factory
from app.llm import build_llm
from app.models import Document
from app.services.documents import document_ref
from team_modules.factory import build_modules


def reindex(settings):
    engine = build_engine(settings.database_url)
    sessions = session_factory(engine)
    llm = build_llm(settings)
    modules = build_modules(settings=settings, llm=llm)
    try:
        with sessions() as db:
            ids = list(
                db.scalars(
                    select(Document.id).where(
                        Document.deleted_at.is_(None), Document.parse_status == "ready"
                    )
                )
            )
        for did in ids:
            with sessions() as db:
                doc = db.get(Document, did)
                reference = document_ref(db, doc)
            result = modules.main_rag.ingest(reference)
            with sessions() as db:
                begin_write(db)
                doc = db.get(Document, did)
                if doc.deleted_at is not None or doc.version != reference.version:
                    db.rollback()
                    continue
                doc.index_version, doc.chunk_count = result.index_version, result.chunk_count
                doc.index_status, doc.error_message = "ready", None
                db.commit()
            print(f"document={did} chunks={result.chunk_count} index={result.index_version}")
    finally:
        llm.close()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["reindex"])
    parser.parse_args()
    reindex(get_settings())
