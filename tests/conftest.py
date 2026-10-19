import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base, get_db, make_engine
from app.main import app
from app.models import User
from app.storage import sha256


def minimal_pdf(text="Response within 4 hours") -> bytes:
    # Small, self-contained PDF fixture. Real Chinese documents are tested separately.
    content = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    startxref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n".encode())
    return output.getvalue()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BID_STORAGE_PATH", str(tmp_path / "blobs"))
    monkeypatch.setenv("BID_DEMO_ENABLED", "false")  # Tests must not inherit Compose's local demo setting.
    get_settings.cache_clear()
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([User(name="owner", api_key_hash=sha256(b"owner-test-api-key-long-enough")),
                    User(name="outsider", api_key_hash=sha256(b"outsider-test-api-key-long"))])
    def db_override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as client:
        client.headers["X-API-Key"] = "owner-test-api-key-long-enough"
        yield client, factory, get_settings()
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    engine.dispose()


def upload(client, project_id, content=None, key="upload-request-0001"):
    return client.post(f"/api/v1/projects/{project_id}/documents",
                       data={"title": "Tender", "kind": "TENDER"},
                       files={"file": ("tender.pdf", content or minimal_pdf(), "application/pdf")},
                       headers={"Idempotency-Key": key})
