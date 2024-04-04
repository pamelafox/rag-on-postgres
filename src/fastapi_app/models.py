from __future__ import annotations

from dataclasses import asdict

from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column


# Define the models
class Base(DeclarativeBase, MappedAsDataclass):
    pass


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column()
    brand: Mapped[str] = mapped_column()
    name: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column()
    price: Mapped[float] = mapped_column()
    embedding: Mapped[Vector] = mapped_column(Vector(1536))

    def to_dict(self, include_embedding: bool = False):
        model_dict = asdict(self)
        if include_embedding:
            model_dict["embedding"] = model_dict["embedding"].tolist()
        else:
            del model_dict["embedding"]
        return model_dict
