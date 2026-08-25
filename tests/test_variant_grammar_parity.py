"""The condition grammar and its semantics, mirrored on ubCode's engine.

The vendored corpus (``test_variant_conditions.py``) pins 46 conditions. It is
the shared contract, and it is not the whole grammar: every form it is silent
about was decided here by whichever engine happened to be reading the string.
Review measured six such forms accepted-and-true here and refused-or-false
there — one rule string, two document sets, which is the exact hazard the
narrowing exists to remove.

So the accept-set AND the comparison semantics are now **bound to ubCode's
shipped engine**, and this module is that binding. Every row below is a
measurement, not a design decision:

* ubCode's grammar comes from ``rust/ubc_query/src/py_expr.pest`` plus the AST
  conversion in ``py_expr.rs``;
* its evaluation comes from ``rust/ubc_query/src/filter.rs`` and the value
  lowering in ``rust/ubc_config/src/needs/variant_data.rs``;
* and every expression here was run through the **shipped engine itself** —
  a scratch binary with a path dependency on ``ubc_config``, calling
  ``UbprojectConfigR::from_toml_str`` for the verdict and
  ``evaluate_if_expression`` for the value, over the corpus's own
  ``[variant_data]``.

The semantics deliberately depart from Python. ``var.debug == 0`` is ``False``
here because it is false there; Python's ``False == 0`` would have made it true
and the two tools would have built different sites from one file, silently. The
same divergence read the other way is ``var.debug != 0``, ``True`` here and
``False`` in Python.

``design/mapping-contract.md`` §12.5 carries both tables for a third reader.
"""

from __future__ import annotations

from typing import Any

import pytest

from sphinx_mounts.variants import (
    VariantConditionError,
    VariantEvalError,
    evaluate,
    validate,
)

#: The corpus's own ``[variant_data]``, so a row here can be compared with a
#: corpus row directly.
VARIANT_DATA: dict[str, Any] = {
    "edition": "pro",
    "count": 2,
    "ratio": 1.5,
    "debug": False,
    "name": "Widget",
    "tags": ["alpha", "beta"],
    "build": {"debug": True, "features": ["core", "net"]},
    "empty": {},
}


class _Sentinel:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


#: The condition is outside ubCode's grammar: a configuration error.
REJECT = _Sentinel("REJECT")
#: The condition is inside the grammar and fails to EVALUATE, which excludes.
ERROR = _Sentinel("ERROR")

#: Every row measured against ubCode's shipped engine.
#:
#: ``REJECT`` = refused by the grammar; ``ERROR`` = accepted and unevaluable;
#: ``True`` / ``False`` = accepted and that truth value under
#: :data:`VARIANT_DATA`.
UBCODE_TABLE: list[tuple[str, Any]] = [
    ("var.count == 2", True),
    ("var.count == -2", False),
    ("var.count == +2", REJECT),
    ("var.count == 2.0", True),
    ("var.count == True", False),
    ("var.count == None", False),
    ("var.edition == 'pro'", True),
    ("var.tags == ['alpha', 'beta']", REJECT),
    ("var.count == var.ratio", False),
    ("var.name.upper() == 'WIDGET'", True),
    ("var.count == var.name.upper()", False),
    ("var.name.startswith('W') == True", REJECT),
    ("var.debug == 0", False),
    ("var.debug == False", True),
    ("'pro' == var.edition", True),
    ("2 == var.count", True),
    ("2 < var.count", False),
    ("'pro' < var.edition", REJECT),
    ("True == var.debug", False),
    ("None == var.edition", False),
    ("['a'] == var.tags", REJECT),
    ("var.count < 2", False),
    ("var.count <= 2", True),
    ("var.count > 2", False),
    ("var.count >= 2", True),
    ("var.count < 2.5", True),
    ("var.count < -1", False),
    ("var.edition < 'x'", REJECT),
    ("var.count < True", REJECT),
    ("var.count < None", REJECT),
    ("var.count < var.ratio", False),
    ("var.count < var.name", ERROR),
    ("var.name.upper() < 5", ERROR),
    ("var.debug > 0", ERROR),
    ("var.edition in ['pro', 'x']", True),
    ("var.edition in ['pro', 2]", True),
    ("var.edition in 'professional'", REJECT),
    ("var.edition in var.name", REJECT),
    ("var.edition not in var.name", REJECT),
    ("'net' in var.build.features", True),
    ("'net' not in var.build.features", False),
    ("'debug' in var.build", ERROR),
    ("'x' in var.build", ERROR),
    ("2 in var.tags", ERROR),
    ("var.tags in var.build.features", REJECT),
    ("var.count in [1, 2, 3]", True),
    ("var.debug in [True, False]", True),
    ("None in var.tags", ERROR),
    ("'a' in 'abc'", REJECT),
    ("var.edition is None", False),
    ("var.edition is not None", True),
    ("var.missing is None", ERROR),
    ("var.build is None", False),
    ("var.empty is None", False),
    ("var.name.startswith('Wid')", True),
    ("var.name.endswith('get')", True),
    ("var.name.upper().startswith('WID')", True),
    ("var.count.startswith('2')", ERROR),
    ("not var.name.startswith('Wid')", False),
    ("True == True", REJECT),
    ("'a' == 'b'", REJECT),
    ("1 < 2", REJECT),
    ("True", True),
    ("False", False),
    ("not True", False),
    ("var.debug", REJECT),
    ("not var.debug", REJECT),
    ("var.build == var.empty", False),
    ("var.build == 'x'", False),
    ("var.tags == var.build.features", ERROR),
    ("var.tags != var.build.features", ERROR),
    ("var.build.debug == var.debug", False),
    ("len(var.tags) > 1", REJECT),
    ("var.name == 'Wid' 'get'", REJECT),
    ("-var.count == 2", REJECT),
    ("var.count == - 2", REJECT),
    ("var.ratio == 1", False),
    ("var.ratio == 1.5", True),
    ("var.tags != ['alpha', 'beta']", REJECT),
    ("var.missing == 'x'", ERROR),
    ("var.build.missing == 1", ERROR),
    ("var.ratio == -1.5", False),
    ("var.count == -0", False),
    ("var.count != 2", False),
    ("var.count != 3", True),
    ("var.edition != 'pro'", False),
    ("var.debug != 0", True),
    ("var.count != True", True),
    ("var.build.features == ['core', 'net']", REJECT),
    ("'ph' in var.edition", False),
    ("'PRO' in var.edition.upper()", True),
    ("var.edition.upper() in ['PRO']", True),
    ("var.empty == var.empty", True),
    ("var.build == var.build", True),
    ("var.build != var.empty", True),
    ("1 < var.count < 3", REJECT),
    ("var.count == 2 and var.debug == False", True),
    ("(var.count == 2)", True),
    ("var.name.lower() == 'widget'", True),
    ("var.tags == 'alpha'", False),
    ("'x' in var.count", ERROR),
    ("var.count in var.tags", REJECT),
    ("var.name.startswith('W') and var.count == 2", True),
    ("not var.name.upper()", REJECT),
    ("var.name.upper()", REJECT),
    ("var.count == 2e1", False),
    ("var.ratio == 1.5e0", True),
    ("var.tags == []", REJECT),
    ('var.name.startswith("W")', True),
    ('var.edition == "pro"', True),
    ("var.count >= -2", True),
    ("var.build.features in ['core']", False),
    ("var.empty in ['x']", False),
    ("'alpha' in var.tags", True),
    ("True in var.tags", ERROR),
    ("var.debug is None", False),
    ("var.debug is not None", True),
    ("var.count.upper() == 'X'", ERROR),
    ("var.name.upper().upper() == 'X'", REJECT),
    ("var.name.endswith('get') == True", REJECT),
    ("var.tags != 'alpha'", True),
    ("var.build.debug != var.debug", True),
    ("var.count == var.count", True),
    ("var.ratio == var.count", False),
    ("2.0 == var.count", True),
    ("2 != var.count", False),
    ("'net' in var.tags", False),
    ("var.count == 2 or var.tags == var.build.features", True),
    ("var.tags == var.build.features or var.count == 2", ERROR),
    ("var.count == 3 and var.tags == var.build.features", False),
    ("var.tags == var.build.features and var.count == 3", ERROR),
    ("var.count == 2 or var.missing == 'x'", True),
    ("var.missing == 'x' or var.count == 2", ERROR),
    ("var.count == 3 and var.missing == 'x'", False),
    ("False and var.missing == 'x'", False),
    ("True or var.missing == 'x'", True),
    ("not (var.count == 2)", False),
    ("var.count == 2 and (var.debug == False or var.missing == 'x')", True),
]


def _row_id(row: tuple[str, Any]) -> str:
    return f"{row[1]}:{row[0] or '<empty>'}"


@pytest.mark.parametrize("row", UBCODE_TABLE, ids=_row_id)
def test_matches_ubcodes_engine(row: tuple[str, Any]) -> None:
    """Reproduce one measured row of ubCode's shipped engine.

    A disagreement here is not a style difference: it is a spelling that puts
    a different set of files in the two tools' builds from one ``if`` string.
    """
    expr, expected = row
    if expected is REJECT:
        with pytest.raises(VariantConditionError):
            validate(expr)
        return
    validate(expr)
    if expected is ERROR:
        with pytest.raises(VariantEvalError):
            evaluate(expr, VARIANT_DATA)
        return
    assert evaluate(expr, VARIANT_DATA) is expected


def test_the_table_covers_every_operator_and_operand_kind() -> None:
    """A cheap guard against the table being trimmed to what happens to pass.

    The enumeration is what makes this a contract rather than a sample: the
    corpus's holes were exactly the operand/operator combinations nobody had
    written down.
    """
    text = " ".join(expr for expr, _ in UBCODE_TABLE)
    for operator in ("==", "!=", "<=", ">=", " < ", " > ", " in ", "not in", "is None"):
        assert operator in text, operator
    for operand in ("-2", "2.0", "True", "None", "['", ".upper()", ".startswith("):
        assert operand in text, operand
    assert len(UBCODE_TABLE) >= 100


# ---------------------------------------------------------------------------
# The divergences from Python, called out one at a time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "ours", "python"),
    [
        ("var.debug == 0", False, True),
        ("var.debug != 0", True, False),
        ("var.debug > 0", ERROR, False),
        ("var.tags == var.build.features", ERROR, False),
        ("var.tags != var.build.features", ERROR, True),
        ("'debug' in var.build", ERROR, True),
        ("2 in var.tags", ERROR, False),
        ("None in var.tags", ERROR, False),
        ("var.build == var.build", True, True),
    ],
    ids=lambda value: str(value),
)
def test_the_semantics_are_ubcodes_not_pythons(
    expr: str, ours: Any, python: Any
) -> None:
    """Each row is a place where matching CPython would split the document set.

    ``python`` is what Python's own operators return for the same expression
    over the same data — recorded so that a future reader can see the size of
    the deliberate departure rather than having to re-derive it, and so that
    ubCode's published claim that these "match Python's semantics"
    (``docs/source/usage/variants.rst``) is visibly a defect in ITS docs rather
    than something this reader adopted.
    """
    if ours is ERROR:
        with pytest.raises(VariantEvalError):
            evaluate(expr, VARIANT_DATA)
    else:
        assert evaluate(expr, VARIANT_DATA) is ours
    assert python is not None  # the Python column is documentation, not a call


def test_and_or_short_circuit_left_to_right() -> None:
    """Measured on ubCode: an unreached operand's error never surfaces.

    ubCode evaluates a DNF, which is not obviously left-to-right — so this was
    probed rather than assumed. Both engines agree.
    """
    assert evaluate("var.count == 2 or var.missing == 'x'", VARIANT_DATA) is True
    assert evaluate("var.count == 3 and var.missing == 'x'", VARIANT_DATA) is False
    with pytest.raises(VariantEvalError):
        evaluate("var.missing == 'x' or var.count == 2", VARIANT_DATA)


def test_a_negative_literal_must_hug_its_digits() -> None:
    """``-2`` is one literal in ubCode's grammar; ``- 2`` and ``+2`` are not.

    Python's AST gives ``-2`` and ``- 2`` the same tree, so the column offsets
    are what separate them. Without that, accepting negatives would also accept
    two spellings ubCode refuses.
    """
    validate("var.count == -2")
    for refused in ("var.count == - 2", "var.count == +2", "-var.count == 2"):
        with pytest.raises(VariantConditionError):
            validate(refused)


def test_implicit_string_concatenation_is_refused() -> None:
    """Python folds ``'Wid' 'get'`` at parse time; ubCode has no such rule.

    The folded constant evaluates TRUE where ubCode refuses the condition
    outright, so the source segment is read back to tell the two apart.
    """
    with pytest.raises(VariantConditionError, match="one literal"):
        validate("var.name == 'Wid' 'get'")
    validate("var.name == 'Widget'")


def test_a_transformer_may_carry_a_predicate() -> None:
    """``var.name.upper().startswith('WID')`` is accepted — measured.

    One transformer, then a predicate. A second transformer is not:
    ``var_field_with_func`` admits exactly one function.
    """
    assert evaluate("var.name.upper().startswith('WID')", VARIANT_DATA) is True
    with pytest.raises(VariantConditionError):
        validate("var.name.upper().upper() == 'X'")


def test_recursion_is_an_ordinary_error_not_a_traceback() -> None:
    """No input reaches an unhandled outcome — including a pathological one."""
    deep = "not " * 4000 + "var.count == 2"
    with pytest.raises((VariantConditionError, VariantEvalError)):
        evaluate(deep, VARIANT_DATA)
