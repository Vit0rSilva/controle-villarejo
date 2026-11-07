"""Initial schema with pg_trgm, unaccent, categories, products and stock_logs

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-06 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # Ativa extensões do PostgreSQL para busca textual tolerante a erros e sem acentos
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        op.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

    # Tabela categories
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.String()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="{}" if is_postgres else "[]",
        ),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_update_source", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"], unique=True)

    # Enum stock_status_enum
    stock_status_enum = sa.Enum(
        "OK",
        "WARNING",
        "CRITICAL",
        "NEEDS_ACTION",
        name="stock_status_enum",
    )

    # Tabela products
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "category_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canonical_name", sa.String(length=180), nullable=False),
        sa.Column("normalized_name", sa.String(length=180), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("raw_main_value", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("numeric_quantity", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column(
            "sub_attributes",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("stock_status", stock_status_enum, nullable=False, server_default="OK"),
        sa.Column("needs_restock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_incomplete_data", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_products_category_id", "products", ["category_id"], unique=False)
    op.create_index("ix_products_canonical_name", "products", ["canonical_name"], unique=False)
    op.create_index("ix_products_normalized_name", "products", ["normalized_name"], unique=False)
    op.create_index("ix_products_needs_restock", "products", ["needs_restock"], unique=False)

    if is_postgres:
        # Índices GIN Trigram para busca aproximada ultra-rápida no PostgreSQL
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_products_normalized_name_trgm "
            "ON products USING gin (normalized_name gin_trgm_ops);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_products_canonical_name_trgm "
            "ON products USING gin (canonical_name gin_trgm_ops);"
        )

    # Tabela stock_logs
    op.create_table(
        "stock_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("instance_name", sa.String(length=120), nullable=False),
        sa.Column("sender_phone", sa.String(length=64), nullable=True),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("parsed_items_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "unrecognized_lines",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.drop_table("stock_logs")
    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_products_normalized_name_trgm;")
        op.execute("DROP INDEX IF EXISTS ix_products_canonical_name_trgm;")
    op.drop_index("ix_products_needs_restock", table_name="products")
    op.drop_index("ix_products_normalized_name", table_name="products")
    op.drop_index("ix_products_canonical_name", table_name="products")
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_table("products")

    if is_postgres:
        op.execute("DROP TYPE IF EXISTS stock_status_enum;")

    op.drop_index("ix_categories_slug", table_name="categories")
    op.drop_table("categories")
