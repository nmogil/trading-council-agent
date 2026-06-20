from sqlalchemy import inspect
from sqlmodel import select

from trading_council import db
from trading_council.models import Member

EXPECTED_TABLES = {
    "member",
    "proposal",
    "vote",
    "trade_order",
    "position",
    "portfolio_snapshot",
    "audit_log",
}


def test_init_db_creates_parent_dir_and_tables(tmp_path):
    db_path = tmp_path / "nested" / "trading_council.db"
    engine = db.init_db(f"sqlite:///{db_path}")

    assert db_path.parent.is_dir()
    assert db_path.exists()
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_get_session_roundtrip(tmp_path):
    engine = db.init_db(f"sqlite:///{tmp_path / 'tc.db'}")
    with db.get_session(engine) as session:
        session.add(Member(id="42", display_name="Alice"))
        session.commit()

    with db.get_session(engine) as session:
        assert session.exec(select(Member)).one().display_name == "Alice"


def test_in_memory_url_needs_no_directory():
    engine = db.init_db("sqlite://")  # must not raise creating a parent dir
    assert "member" in set(inspect(engine).get_table_names())
