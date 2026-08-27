"""Initial schema — ALPHA BIST v1.0.

Revision ID: 001_initial
Revises: None
Create Date: 2026-08-25
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial schema tables."""

    # === REFERENCE DATA ===
    op.create_table(
        "sectors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100)),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("sectors.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sector_id", sa.Integer, sa.ForeignKey("sectors.id"), nullable=True),
        sa.Column("market_cap", sa.BigInteger),
        sa.Column("free_float_ratio", sa.Numeric(5, 4)),
        sa.Column("isin", sa.String(20)),
        sa.Column("founded_year", sa.Integer),
        sa.Column("employee_count", sa.Integer),
        sa.Column("website", sa.String(200)),
        sa.Column("description", sa.Text),
        sa.Column("kap_id", sa.String(50)),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("symbol", sa.String(20), unique=True, nullable=False),
        sa.Column("isin", sa.String(20)),
        sa.Column("instrument_type", sa.String(20), server_default="EQUITY"),
        sa.Column("exchange", sa.String(20), server_default="BIST"),
        sa.Column("lot_size", sa.Integer, server_default="1"),
        sa.Column("tick_size", sa.Numeric(10, 6)),
        sa.Column("trading_hours_start", sa.Time, server_default="10:00"),
        sa.Column("trading_hours_end", sa.Time, server_default="18:00"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === PORTFOLIO ===
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(50), server_default="quant"),
        sa.Column("initial_capital", sa.Numeric(15, 2), nullable=False),
        sa.Column("cash", sa.Numeric(15, 2), nullable=False),
        sa.Column("total_value", sa.Numeric(15, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("avg_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("current_price", sa.Numeric(12, 4)),
        sa.Column("unrealized_pnl", sa.Numeric(15, 2)),
        sa.Column("realized_pnl", sa.Numeric(15, 2), server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),  # BUY/SELL
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("commission", sa.Numeric(10, 2), server_default="0"),
        sa.Column("tax", sa.Numeric(10, 2), server_default="0"),
        sa.Column("total_cost", sa.Numeric(15, 2)),
        sa.Column("order_type", sa.String(20), server_default="MARKET"),
        sa.Column("status", sa.String(20), server_default="FILLED"),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("signal_id", sa.String(50)),
        sa.Column("notes", sa.Text),
    )

    # === ML MODELS ===
    op.create_table(
        "ml_models",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False),  # lightgbm, xgboost, catboost, lstm
        sa.Column("features", sa.JSON),
        sa.Column("hyperparams", sa.JSON),
        sa.Column("metrics", sa.JSON),
        sa.Column("file_path", sa.String(500)),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("trained_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === SIGNALS ===
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("signal_type", sa.String(20), nullable=False),  # BUY/SELL/HOLD
        sa.Column("score", sa.Numeric(8, 4)),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("source", sa.String(50)),  # ml, rule, agent
        sa.Column("model_id", sa.Integer, sa.ForeignKey("ml_models.id"), nullable=True),
        sa.Column("features", sa.JSON),
        sa.Column("reasoning", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )

    # === ALERTS ===
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("ticker", sa.String(20)),
        sa.Column("severity", sa.String(20), server_default="INFO"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("data", sa.JSON),
        sa.Column("acknowledged", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === AUDIT LOG ===
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50)),
        sa.Column("entity_id", sa.String(50)),
        sa.Column("user_id", sa.String(50)),
        sa.Column("details", sa.JSON),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === LEARNING HISTORY ===
    op.create_table(
        "learning_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.Integer, sa.ForeignKey("ml_models.id"), nullable=False),
        sa.Column("ticker", sa.String(20)),
        sa.Column("predicted_direction", sa.String(10)),
        sa.Column("actual_direction", sa.String(10)),
        sa.Column("predicted_score", sa.Numeric(8, 4)),
        sa.Column("actual_return", sa.Numeric(8, 4)),
        sa.Column("brier_score", sa.Numeric(8, 6)),
        sa.Column("is_correct", sa.Boolean),
        sa.Column("features_snapshot", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === INDEXES ===
    op.create_index("idx_companies_ticker", "companies", ["ticker"])
    op.create_index("idx_instruments_symbol", "instruments", ["symbol"])
    op.create_index("idx_positions_portfolio", "positions", ["portfolio_id"])
    op.create_index("idx_trades_portfolio", "trades", ["portfolio_id"])
    op.create_index("idx_trades_executed", "trades", ["executed_at"])
    op.create_index("idx_signals_ticker", "signals", ["ticker"])
    op.create_index("idx_signals_created", "signals", ["created_at"])
    op.create_index("idx_alerts_type", "alerts", ["alert_type"])
    op.create_index("idx_alerts_created", "alerts", ["created_at"])
    op.create_index("idx_learning_model", "learning_history", ["model_id"])
    op.create_index("idx_learning_ticker", "learning_history", ["ticker"])
    op.create_index("idx_audit_action", "audit_log", ["action"])


def downgrade() -> None:
    """Drop all tables."""
    tables = [
        "learning_history", "audit_log", "alerts", "signals", "ml_models",
        "trades", "positions", "portfolios", "instruments", "companies", "sectors",
    ]
    for table in tables:
        op.drop_table(table)
