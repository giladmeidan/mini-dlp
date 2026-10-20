from sqlalchemy import inspect


def test_tables_exist(engine):
    tables = set(inspect(engine).get_table_names())

    assert {"data_types", "data_sets", "data_set_data_types"} <= tables


def test_data_types_check_constraints(engine):
    names = {ck["name"] for ck in inspect(engine).get_check_constraints("data_types")}

    assert names == {
        "ck_data_types_type_allowed",
        "ck_data_types_content_not_empty",
        "ck_data_types_threshold_positive",
    }


def test_case_insensitive_unique_name_indexes(engine):
    inspector = inspect(engine)

    for table in ("data_types", "data_sets"):
        indexes = {ix["name"]: ix for ix in inspector.get_indexes(table)}
        index = indexes[f"uq_{table}_name_lower"]
        assert index["unique"] is True
        assert index["expressions"] == ["lower(name::text)"]


def test_association_foreign_keys_ondelete(engine):
    fks = {
        fk["referred_table"]: fk for fk in inspect(engine).get_foreign_keys("data_set_data_types")
    }

    assert fks["data_sets"]["options"]["ondelete"] == "CASCADE"
    assert fks["data_types"]["options"]["ondelete"] == "RESTRICT"


def test_association_primary_key_and_index(engine):
    inspector = inspect(engine)

    pk = inspector.get_pk_constraint("data_set_data_types")
    assert pk["constrained_columns"] == ["data_set_id", "data_type_id"]
    index_names = {ix["name"] for ix in inspector.get_indexes("data_set_data_types")}
    assert "ix_data_set_data_types_data_type_id" in index_names
