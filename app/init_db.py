from app.core.db import Base, engine
import app.models.entities  # 必须导入


def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ tables created")


if __name__ == "__main__":
    init_db()