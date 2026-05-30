"""Store structured job salary amounts and currency.

Revision ID: 20260529_0019
Revises: 20260529_0018
Create Date: 2026-05-29
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import sqlalchemy as sa
from alembic import op
from alembic import context


revision: str = "20260529_0019"
down_revision: str | None = "20260529_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("job_postings") as batch_op:
            batch_op.add_column(sa.Column("salary_min", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("salary_max", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("salary_currency", sa.String(length=3), nullable=True))
        op.execute("-- Skipping salary_text backfill in offline SQL generation; run this migration online to backfill salary amounts.")
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("job_postings")}

    with op.batch_alter_table("job_postings") as batch_op:
        if "salary_min" not in existing_columns:
            batch_op.add_column(sa.Column("salary_min", sa.Integer(), nullable=True))
        if "salary_max" not in existing_columns:
            batch_op.add_column(sa.Column("salary_max", sa.Integer(), nullable=True))
        if "salary_currency" not in existing_columns:
            batch_op.add_column(sa.Column("salary_currency", sa.String(length=3), nullable=True))

    rows = list(bind.execute(sa.text("select id, salary_text, source_provider, source from job_postings")).mappings())
    for row in rows:
        salary_min, salary_max, currency = _parse_salary_text(row["salary_text"])
        if currency is None and (row["source_provider"] == "adzuna" or row["source"] == "adzuna"):
            currency = "USD"
        if salary_min is None and salary_max is None and currency is None:
            continue
        bind.execute(
            sa.text(
                """
                update job_postings
                set salary_min = :salary_min,
                    salary_max = :salary_max,
                    salary_currency = :salary_currency
                where id = :id
                """
            ),
            {"id": row["id"], "salary_min": salary_min, "salary_max": salary_max, "salary_currency": currency},
        )


def downgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("job_postings") as batch_op:
            batch_op.drop_column("salary_currency")
            batch_op.drop_column("salary_max")
            batch_op.drop_column("salary_min")
        return

    existing_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_postings")}
    with op.batch_alter_table("job_postings") as batch_op:
        if "salary_currency" in existing_columns:
            batch_op.drop_column("salary_currency")
        if "salary_max" in existing_columns:
            batch_op.drop_column("salary_max")
        if "salary_min" in existing_columns:
            batch_op.drop_column("salary_min")


def _parse_salary_text(value: object) -> tuple[int | None, int | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None, None
    text = value.strip()
    currency_match = re.match(r"^([A-Z]{3})\s+", text)
    currency = currency_match.group(1) if currency_match else ("USD" if "$" in text else None)
    amounts = [_parse_amount(match.group(0)) for match in re.finditer(r"\$?\d[\d,]*(?:\.\d+)?\s*[kK]?", text)]
    amounts = [amount for amount in amounts if amount is not None]
    if not amounts:
        return None, None, currency
    if len(amounts) == 1:
        return amounts[0], None, currency
    return amounts[0], amounts[1], currency


def _parse_amount(value: str) -> int | None:
    cleaned = value.replace("$", "").replace(",", "").strip()
    multiplier = Decimal("1000") if cleaned.lower().endswith("k") else Decimal("1")
    cleaned = cleaned.rstrip("kK").strip()
    try:
        amount = Decimal(cleaned) * multiplier
    except (InvalidOperation, ValueError):
        return None
    if amount < 0:
        return None
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
