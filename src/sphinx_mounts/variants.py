"""Variant conditions and variant data — the ``[[source.variant_sources]]`` engine.

**Import discipline: this module is deliberately dependency-free.** It imports
nothing from :mod:`sphinx_mounts`, nothing from Sphinx and nothing from
docutils — only the standard library. The same is true of
:mod:`sphinx_mounts.dialect`. Both are written that way so that extracting
them into a shared ``sphinx-variants`` package later is a ``git mv`` rather
than a rewrite: the condition grammar is a two-engine contract (see
``tests/fixtures/variant_condition_conformance.toml``), and a contract that
can only live inside a mounting extension is one a second Sphinx extension
cannot adopt without depending on this one.

Anything that needs a Sphinx type — the ``ExtensionError`` wrapping, the
typed ``mounts.*`` warnings, ``config.root_doc`` — belongs in
:mod:`sphinx_mounts.config` or :mod:`sphinx_mounts.extension`, which catch the
plain exceptions raised here and re-raise them in Sphinx's vocabulary.

Two halves:

**The condition engine** (:func:`validate`, :func:`interpret`) is an
*interpreter*, not an :func:`eval` with a small globals dict. ``ast.parse``
produces one tree; :func:`validate` walks it against a whitelist, and
:func:`interpret` walks the *same* tree over the plain merged mapping. There
is no namespace object, no ``var`` binding and no builtins to remove, because
nothing is ever executed. That turns the whitelist's completeness from a
*security* property into a *correctness* one: a node type the interpreter does
not handle raises :class:`VariantEvalError` instead of running.

**The variant-data reader** (:func:`resolve_variant_data`) is a private copy of
sphinx-needs' ``deep_merge`` / ``validate_variant_data`` /
``load_variant_data_file`` semantics. The copy exists so that sphinx-mounts
never imports, depends on, or version-gates against sphinx-needs, and it cannot
disagree with it: ``deep_merge(file, inline)`` is idempotent, so re-merging an
already-merged map is a proven no-op. See :func:`resolve_variant_data`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

#: Leaf value types the variant data may hold.
_SCALAR_TYPES = (str, bool, int, float)


class VariantConditionError(Exception):
    """A rule condition is outside the grammar — a *configuration* error.

    Statically knowable, so it is refused rather than evaluated. The caller
    turns this into a hard, non-suppressible failure.
    """


class VariantEvalError(Exception):
    """A rule condition is inside the grammar but cannot be *evaluated*.

    An unknown ``var.*`` key or a type mismatch. Data-dependent rather than
    statically knowable, so it is reported and the rule is treated as FALSE —
    the warn-and-exclude contract the ``.. if::`` directive already has, and
    the safe direction for a key whose purpose is keeping content out.
    """


class VariantDataError(Exception):
    """The variant data itself is unreadable or malformed.

    Deliberately the same name sphinx-needs uses for the same condition, so a
    reader comparing the two implementations is not misled by a rename.
    """


# ---------------------------------------------------------------------------
# The two bound tables
# ---------------------------------------------------------------------------
#
# The accept-set AND the comparison semantics below are MIRRORED ON UBCODE'S
# SHIPPED ENGINE, derived from its primary sources and confirmed against a live
# probe of it (`rust/ubc_query/src/py_expr.pest`, `py_expr.rs`, `filter.rs`,
# `rust/ubc_config/src/needs/variant_data.rs`). Both tables are reproduced
# verbatim in `design/mapping-contract.md` §12.5, which is the contract a third
# reader implements against.
#
# They deliberately depart from Python in places. That is the point: the same
# `if` string is read by two engines, and "one rule string, one document set"
# is worth more than matching CPython. `var.debug == 0` is FALSE here because
# it is false there — Python's `False == 0` would have made it true and the two
# tools would have built different sites from one file, silently.
#
# ubCode's own `docs/source/usage/variants.rst` claims the semantics match
# Python's. Measured, they do not; that is a defect in ubCode's documentation,
# named here rather than adopted. If the two engines ever move to Python
# semantics they move together, and this module and that engine change in the
# same release.


def _is_var_rooted(node: ast.AST) -> bool:
    """Whether ``node`` is ``var`` or a chain of plain attributes rooted at it.

    A leading-underscore segment is refused outright. Nothing can reach
    ``__class__`` through the interpreter anyway — it holds no objects, only
    the plain mapping — but refusing the spelling keeps the *grammar* the same
    shape as the one a future ``eval``-based reader would need.
    """
    while isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            return False
        node = node.value
    return isinstance(node, ast.Name) and node.id == "var"


def _dotted(node: ast.AST) -> str:
    """Render an attribute chain / name as the author wrote it."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    parts.reverse()
    return ".".join(parts)


def _refuse_bare_name(name: str) -> None:
    """Raise the right message for a field reference not rooted at ``var``.

    ``true`` / ``false`` get their own sentence because they are by far the
    likeliest way a bare name appears: a TOML author writes the spelling TOML
    uses, and the parser reads it as a *field name*. Saying "write ``var.false``"
    would be accurate and useless.
    """
    if name.startswith("var."):
        # Rooted at `var`, but some segment starts with an underscore.
        msg = (
            f"`{name}` accesses a leading-underscore field, which a rule "
            f"condition may not name; variant data keys are ordinary names"
        )
        raise VariantConditionError(msg)
    if name in {"true", "false"}:
        python = "True" if name == "true" else "False"
        msg = (
            f"`{name}` is read as a field name, not as a boolean: a condition "
            f"is an expression rather than a TOML value, so the literals are "
            f"Python-spelled — write `{python}`"
        )
        raise VariantConditionError(msg)
    msg = (
        f"`{name}` is not rooted at `var`; a rule condition may only reference "
        f"the variant data, so write `var.{name}`. Unlike the `if` directive, "
        f"the leading `var` is required here: a bare name is not expected to be "
        f"defined for every tool that reads this file, and would then select a "
        f"different set of documents"
    )
    raise VariantConditionError(msg)


# ---------------------------------------------------------------------------
# TABLE 1 — the accept-set
# ---------------------------------------------------------------------------
#
# Every shape the grammar admits, and nothing else. Established from ubCode's
# pest grammar plus its AST conversion, and confirmed by probing the shipped
# engine; the probe transcript is quoted in the build report.
#
# An expression is a boolean form:
#
#   boolean := boolean ('and'|'or') boolean
#            | 'not' boolean
#            | '(' boolean ')'
#            | comparison
#            | 'True' | 'False'
#            | receiver '.' ('startswith'|'endswith') '(' string ')'
#
# A comparison is exactly one of these seven rows — note that EVERY row carries
# at least one receiver, because ubCode has no DNF arm holding two literals
# (`True == True` and `'a' == 'b'` are parse errors there, not choices):
#
#   receiver ('=='|'!=') receiver | scalar-literal
#   scalar-literal ('=='|'!=') receiver
#   receiver ('<'|'>'|'<='|'>=') receiver | number-literal
#   number-literal ('<'|'>'|'<='|'>=') receiver
#   receiver ('in'|'not in') '[' scalar-literal, … ']'
#   scalar-literal ('in'|'not in') receiver
#   receiver ('is'|'is not') 'None'
#
#   receiver       := 'var' ('.' name)+ ('.upper()' | '.lower()')?
#   scalar-literal := string | integer | float | 'True' | 'False' | 'None'
#                     (integers and floats may carry a leading '-')
#   number-literal := integer | float, negatives included; NOT bool, None or
#                     string
#
# The consequences that today's Python-shaped whitelist got wrong, each a
# measured divergence rather than a tightening for its own sake:
#
#   * a list literal is legal ONLY as the right-hand side of `in`/`not in`
#     (`var.tags == ['alpha','beta']` → ubCode refuses, Python evaluates TRUE);
#   * `in`/`not in` never take a string or a field on the right
#     (`var.edition in 'professional'`, `var.edition not in var.name` → ubCode
#     refuses, Python evaluates TRUE);
#   * a predicate call cannot appear inside a comparison
#     (`var.name.startswith('W') == True` → refused; `.upper()` inside one is
#     fine, which is the asymmetry an author will not guess);
#   * an ordering operator takes only a number on the literal side
#     (`var.edition < 'x'`, `var.count < True` → refused);
#   * a comparison with no receiver at all is refused;
#   * a NEGATIVE numeric literal is ACCEPTED (`var.count == -2`) — ubCode's
#     `integer_literal` carries `"-"?` — while a unary `+` is refused;
#   * implicit string concatenation (`'Wid' 'get'`) is refused: Python folds it
#     at parse time and ubCode's grammar has no such rule.

#: Methods usable on a ``var.*`` chain, split by RETURN TYPE.
#:
#: The boolean-top-level rule is type-aware and the conformance corpus is what
#: says so: rows 16/17 ACCEPT a bare ``var.name.startswith('Wid')`` /
#: ``.endswith('get')`` (they return ``bool``), while rows 34/35 REJECT a bare
#: ``var.name.upper()`` / ``.lower()`` (they return ``str``). Prose summaries of
#: the grammar — ubCode's own schema doc comment and its ``usage/variants.rst``
#: — say "bare string-method calls" are refused, which is imprecise.
_PREDICATE_METHODS = frozenset({"startswith", "endswith"})
_TRANSFORM_METHODS = frozenset({"upper", "lower"})

_ORDER_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_EQ_OPS = (ast.Eq, ast.NotEq)
_IN_OPS = (ast.In, ast.NotIn)
_IS_OPS = (ast.Is, ast.IsNot)


def _receiver(node: ast.AST) -> ast.AST | None:
    """Return the ``var.*`` chain ``node`` reads, or ``None``.

    A receiver is a ``var``-rooted attribute chain, optionally carrying ONE
    transformer suffix (``.upper()`` / ``.lower()``). ubCode's
    ``var_field_with_func`` is exactly this, and it admits only one function —
    ``var.name.upper().upper()`` is a parse error there, so it is refused here.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _TRANSFORM_METHODS
            and not node.args
            and not node.keywords
            and _is_var_rooted(func.value)
            and isinstance(func.value, ast.Attribute)
        ):
            return func.value
        return None
    if isinstance(node, ast.Attribute) and _is_var_rooted(node):
        return node
    return None


def _is_single_string_literal(text: str, node: ast.Constant) -> bool:
    """Whether a string ``Constant`` came from ONE quoted literal.

    Python folds implicit concatenation (``'Wid' 'get'``) into a single
    ``Constant`` at parse time, so the AST cannot tell the two apart — but
    ubCode's grammar has no concatenation rule, and the folded value evaluates
    TRUE where ubCode refuses the whole condition. The source segment is the
    only place the difference survives, so it is read back.
    """
    segment = ast.get_source_segment(text, node)
    if segment is None:  # pragma: no cover - defensive
        return True
    segment = segment.strip()
    if len(segment) < _SHORTEST_QUOTED or segment[0] not in "'\"":
        # A prefixed form (b'', f'', r'') — not a plain string literal anyway.
        return False
    quote = segment[0]
    index = 1
    while index < len(segment):
        char = segment[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index == len(segment) - 1
        index += 1
    return False  # pragma: no cover - unterminated cannot parse


def _negative_literal_kind(node: ast.UnaryOp) -> str | None:
    """Classify a ``-2`` / ``-1.5`` literal, or return ``None``.

    ubCode's ``integer_literal = @{ "-"? ~ … }`` makes the sign part of the
    literal — but only when it is written against the digits. ``- 2`` and
    ``+2`` are parse errors there, and Python's AST gives ``-2`` and ``- 2``
    the same tree, so the column offsets are what separate them.
    """
    if not isinstance(node.op, ast.USub):
        return None
    operand = node.operand
    if not isinstance(operand, ast.Constant) or isinstance(operand.value, bool):
        return None
    if not isinstance(operand.value, int | float):
        return None
    if operand.col_offset != node.col_offset + 1:
        return None
    return "int" if isinstance(operand.value, int) else "float"


def _literal_kind(text: str, node: ast.AST) -> str | None:
    """Classify ``node`` as a scalar literal, or return ``None``.

    Returns one of ``"str"``, ``"bool"``, ``"int"``, ``"float"``, ``"null"``.
    """
    if isinstance(node, ast.UnaryOp):
        return _negative_literal_kind(node)
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, str):
        # The one kind that needs the source back: Python folds implicit
        # concatenation into a single Constant, and ubCode has no such rule.
        return "str" if _is_single_string_literal(text, node) else None
    for kind, python_type in _CONSTANT_KINDS:
        if isinstance(value, python_type):
            return kind
    return "null" if value is None else None


def _value_kind(node: ast.AST) -> str:
    """The kind of an ALREADY-VALIDATED literal, without consulting the source.

    :func:`_literal_kind` needs the source text to tell ``-2`` from ``- 2`` and
    one string literal from an implicitly concatenated pair. Both are
    validation-only questions — by evaluation time the condition has already
    been accepted — so the interpreter uses this instead and stays a pure
    function of the tree.
    """
    if isinstance(node, ast.UnaryOp):
        operand = node.operand
        if isinstance(operand, ast.Constant) and isinstance(operand.value, int):
            return "int"
        return "float"
    if not isinstance(node, ast.Constant):  # pragma: no cover - validated
        msg = f"cannot evaluate `{type(node).__name__}` as a literal"
        raise VariantEvalError(msg)
    value = node.value
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    for kind, python_type in _CONSTANT_KINDS:
        if isinstance(value, python_type):
            return kind
    msg = f"cannot evaluate the literal {value!r}"  # pragma: no cover
    raise VariantEvalError(msg)  # pragma: no cover


def _literal_value(node: ast.AST) -> Any:
    """The value of a node :func:`_literal_kind` accepted."""
    if isinstance(node, ast.UnaryOp):
        operand = node.operand
        if isinstance(operand, ast.Constant) and isinstance(operand.value, int | float):
            # `validate` only admits a negated NUMBER, so this is the only
            # shape that reaches here.
            return -operand.value
    if isinstance(node, ast.Constant):
        return node.value
    msg = f"cannot read a literal from `{type(node).__name__}`"  # pragma: no cover
    raise VariantEvalError(msg)  # pragma: no cover


def _scalar_list(text: str, node: ast.AST) -> list[ast.AST] | None:
    """Return the elements of a list literal of scalars, or ``None``."""
    if not isinstance(node, ast.List | ast.Tuple):
        return None
    for element in node.elts:
        if _literal_kind(text, element) is None:
            return None
    return list(node.elts)


def _refuse_operand(node: ast.AST, *, what: str) -> None:
    """Raise the most specific message available for a rejected operand."""
    if isinstance(node, ast.Name | ast.Attribute):
        _refuse_bare_name(_dotted(node))
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _PREDICATE_METHODS:
            msg = (
                f"`.{func.attr}()` may not appear inside a comparison; it is a "
                f"complete condition on its own. Write "
                f"`var.field.{func.attr}('…')`, optionally negated with `not`"
            )
            raise VariantConditionError(msg)
        name = _dotted(func) if isinstance(func, ast.Name | ast.Attribute) else "?"
        msg = (
            f"unsupported call `{name}`: only `.startswith()`, `.endswith()`, "
            f"`.upper()` and `.lower()` on a `var.*` field are available — there "
            f"are no builtins and no filter functions in a rule condition"
        )
        raise VariantConditionError(msg)
    if isinstance(node, ast.List | ast.Tuple):
        msg = (
            "a list literal is only allowed on the right of `in` / `not in`; "
            "compare against one value at a time, or write "
            "`var.field in ['a', 'b']`"
        )
        raise VariantConditionError(msg)
    if isinstance(node, ast.UnaryOp):
        msg = (
            "a sign is part of a numeric literal, so it must be written "
            "against the digits (`-2`, not `- 2`), and `+` is not accepted"
        )
        raise VariantConditionError(msg)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        msg = (
            "implicit string concatenation is not part of a rule condition; "
            "write the string as one literal"
        )
        raise VariantConditionError(msg)
    msg = (
        f"unsupported {what} `{type(node).__name__}`; a rule condition is "
        f"comparisons, `in` / `not in`, `is None` / `is not None`, "
        f"`.startswith(…)` / `.endswith(…)`, `and` / `or` / `not`, parentheses, "
        f"nested `var.*` access and the literals `True` / `False`"
    )
    raise VariantConditionError(msg)


def _validate_predicate_call(text: str, node: ast.Call) -> None:
    """Validate a terminal ``.startswith(…)`` / ``.endswith(…)`` call."""
    func = node.func
    if not isinstance(func, ast.Attribute):  # pragma: no cover - caller checks
        _refuse_operand(node, what="expression")
        return
    if _receiver(func.value) is None:
        msg = "a string predicate may only be called on a `var.*` field"
        raise VariantConditionError(msg)
    if node.keywords:
        msg = "keyword arguments are not supported"
        raise VariantConditionError(msg)
    if len(node.args) != 1 or _literal_kind(text, node.args[0]) != "str":
        msg = f"`.{func.attr}()` takes exactly one string literal"
        raise VariantConditionError(msg)


def _validate_compare(text: str, node: ast.Compare) -> None:
    """Validate one comparison against TABLE 1's seven rows."""
    if len(node.ops) != 1:
        msg = "chained comparisons are not supported; write them with `and`"
        raise VariantConditionError(msg)
    op = node.ops[0]
    left, right = node.left, node.comparators[0]

    if isinstance(op, _IS_OPS):
        if _receiver(left) is None:
            _refuse_operand(left, what="operand")
        if _literal_kind(text, right) != "null":
            msg = "`is` / `is not` may only be used with `None`"
            raise VariantConditionError(msg)
        return

    if isinstance(op, _IN_OPS):
        if _receiver(right) is not None:
            # `literal in var.field` — the container is the field.
            if _literal_kind(text, left) is None:
                _refuse_operand(left, what="left operand")
            return
        elements = _scalar_list(text, right)
        if elements is None:
            if isinstance(right, ast.Name | ast.Attribute):
                _refuse_bare_name(_dotted(right))
            msg = (
                "the right of `in` / `not in` must be a list literal of scalars "
                "(`var.field in ['a', 'b']`) or a `var.*` field with a literal "
                "on the left (`'a' in var.field`). A string or a field on the "
                "right is refused, because it is not part of the shared grammar"
            )
            raise VariantConditionError(msg)
        if _receiver(left) is None:
            _refuse_operand(left, what="left operand")
        return

    if isinstance(op, _EQ_OPS):
        _validate_symmetric(text, left, right, literal_kinds=None)
        return

    if isinstance(op, _ORDER_OPS):
        _validate_symmetric(text, left, right, literal_kinds=("int", "float"))
        return

    msg = f"unsupported comparison operator `{type(op).__name__}`"
    raise VariantConditionError(msg)


def _validate_symmetric(
    text: str,
    left: ast.AST,
    right: ast.AST,
    *,
    literal_kinds: tuple[str, ...] | None,
) -> None:
    """Validate an equality or ordering comparison.

    At least one side must be a receiver; the other may be a receiver or a
    literal of ``literal_kinds`` (``None`` meaning any scalar literal). Both
    sides being literals is refused — ubCode has no DNF arm for it.
    """
    left_receiver = _receiver(left) is not None
    right_receiver = _receiver(right) is not None
    if left_receiver and right_receiver:
        return
    if not left_receiver and not right_receiver:
        if (
            _literal_kind(text, left) is not None
            and _literal_kind(text, right) is not None
        ):
            msg = (
                "a comparison must reference the variant data; a comparison "
                "between two literals is always the same answer and is not part "
                "of the shared grammar"
            )
            raise VariantConditionError(msg)
        _refuse_operand(left if _receiver(left) is None else right, what="operand")
    literal_side = right if left_receiver else left
    kind = _literal_kind(text, literal_side)
    if kind is None:
        _refuse_operand(literal_side, what="operand")
    if literal_kinds is not None and kind not in literal_kinds:
        msg = (
            f"`<`, `>`, `<=` and `>=` compare numbers, so the other side must "
            f"be a number literal or another `var.*` field; got a {kind} literal"
        )
        raise VariantConditionError(msg)


def _refuse_non_boolean(node: ast.AST) -> None:
    """Raise for a sub-expression whose value is not a boolean."""
    if isinstance(node, ast.Name | ast.Attribute):
        name = _dotted(node)
        if not _is_var_rooted(node):
            _refuse_bare_name(name)
        msg = (
            f"`{name}` is used as a condition on its own, which is not a "
            f"boolean; compare it instead (for example `{name} == True`)"
        )
        raise VariantConditionError(msg)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        name = f"{_dotted(node.func.value)}.{node.func.attr}()"
        msg = (
            f"`{name}` returns a string, not a boolean, so it cannot be a "
            f"condition on its own; compare it instead (for example "
            f"`{name} == 'VALUE'`)"
        )
        raise VariantConditionError(msg)
    msg = (
        f"a rule condition must be boolean-valued; got "
        f"`{type(node).__name__}`. Write an explicit comparison"
    )
    raise VariantConditionError(msg)


def _validate_boolean(text: str, node: ast.AST) -> None:
    """Validate a boolean-valued sub-expression.

    ``not var.debug`` is refused even though its *top level* is boolean. The
    reason is parity: ubCode enforces the same rule over a flattened DNF, where
    a negation arrives as a negated leaf with nothing left to say whether it was
    the top level, so it refuses both. Narrower is the safe direction for a
    grammar two engines must agree on — a refused form is a configuration error
    the author rewrites once, never a silent disagreement about which documents
    exist. Corpus row: ``not var.debug`` → reject.
    """
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _validate_boolean(text, value)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            _refuse_non_boolean(node)
        _validate_boolean(text, node.operand)
        return
    if isinstance(node, ast.Compare):
        _validate_compare(text, node)
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _PREDICATE_METHODS:
            # Type-aware: `.startswith()` / `.endswith()` return `bool`, so a
            # bare call IS a valid boolean top level (corpus rows 16, 17);
            # `.upper()` / `.lower()` return `str` and are not (rows 34, 35).
            _validate_predicate_call(text, node)
            return
        if isinstance(func, ast.Attribute) and func.attr in _TRANSFORM_METHODS:
            _refuse_non_boolean(node)
        _refuse_operand(node, what="expression")
    _refuse_non_boolean(node)


def validate(expr: str) -> ast.expr:
    """Parse and whitelist-check a rule condition.

    :param expr: The condition exactly as written in ``if = "…"``.
    :return: The validated expression node, ready for :func:`interpret`.
    :raises VariantConditionError: If the condition is outside the grammar.
    """
    text = expr.strip()
    if not text:
        msg = "the condition is empty"
        raise VariantConditionError(msg)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        msg = f"syntax error: {exc.msg}"
        raise VariantConditionError(msg) from exc
    except (ValueError, MemoryError) as exc:  # pragma: no cover - pathological
        msg = f"the condition could not be parsed: {exc}"
        raise VariantConditionError(msg) from exc
    try:
        _validate_boolean(text, tree.body)
    except RecursionError as exc:
        # A deeply nested condition (`not not not …`) blows the walk's stack.
        # The module's discipline is that no input reaches an unhandled
        # outcome, so it becomes an ordinary configuration error.
        msg = "the condition is nested too deeply to interpret"
        raise VariantConditionError(msg) from exc
    return tree.body


# ---------------------------------------------------------------------------
# TABLE 2 — the comparison semantics
# ---------------------------------------------------------------------------
#
# ubCode lowers every variant value to a `FilterValue` and every literal to a
# `UbQueryLiteral`, then decides by an explicit type-pair table
# (`rust/ubc_query/src/filter.rs`). A pair with no arm is FALSE, not an error,
# and a handful of shapes raise instead. Both behaviours are reproduced here;
# neither is Python's.
#
# Value lowering (`rust/ubc_config/src/needs/variant_data.rs`
# `variant_value_to_filter`):
#
#   scalar  -> str | bool | int | float
#   array   -> list[str] | list[bool] | list[int] | list[float]
#              (an EMPTY array lowers to an empty list of STRINGS)
#   mapping -> bool(non-empty)      <- a map is compared by its TRUTHINESS
#
# Equality (`value_matches_literal`, filter.rs:440-462). `!=` is its negation:
#
#   (str, str) (bool, bool) (int, int) (float, float)   -> ==
#   (int, float) -> float(v) == l        (float, int) -> v == float(l)
#   ANY OTHER PAIR                                     -> False
#
#   so (bool, int) is FALSE: `var.debug == 0` is false with `debug = false`,
#   where Python says True. This is the divergence that most changes a
#   document set, and its `!=` twin is `var.debug != 0` -> TRUE here, False in
#   Python.
#
# Field vs field (`EqualVariable`, filter.rs:119-139): the right value is
# converted to a literal first, and a LIST cannot be — that raises. So
# `var.tags == var.build.features` is an EVALUATION ERROR, not `False`.
#
# Ordering (`value_compares_number`, filter.rs:464-500): the left value must be
# int or float, else it RAISES; a field on the right must be int or float, else
# it raises. `var.debug > 0` raises here and is `False` in Python.
#
# Membership, literal in field (`LiteralInVarField`, filter.rs:184-253):
#
#   str        + str literal        -> substring
#   list[str]  + str literal        -> contains
#   list[bool] + bool literal       -> contains
#   list[int]  + int literal        -> contains
#   list[int]  + float literal      -> any(float(i) == l)
#   list[float]+ float literal      -> contains
#   list[float]+ int literal        -> any(f == float(l))
#   any other literal for a list    -> RAISES
#   bool | int | float value        -> RAISES  (a mapping lowers to bool, so
#                                     `'debug' in var.build` RAISES too)
#
# Membership, field in list literal (`VarInLiteralList`, filter.rs:288-312):
#   any(equality table) over the literals; a list value matches nothing.
#
# `is None` / `is not None`: variant data can never hold a null, so a
# resolvable key is never None. An unknown key raises, as everywhere else.
#
# `.upper()` / `.lower()` and the string predicates require a str value and
# raise otherwise (`apply_function`, filter.rs:19-42).

#: The shortest a quoted string literal can be: two quote characters.
_SHORTEST_QUOTED = 2

#: Constant kinds, most specific first — ``bool`` before ``int``, because
#: ``isinstance(True, int)`` is true in Python and the two are DIFFERENT kinds
#: in the semantics table (``(bool, int)`` has no arm).
_CONSTANT_KINDS: tuple[tuple[str, type], ...] = (
    ("bool", bool),
    ("int", int),
    ("float", float),
)

_LIST_KINDS = {"list_str", "list_bool", "list_int", "list_float"}
_NUMBER_KINDS = ("int", "float")


def _lower_list(value: list[Any]) -> tuple[str, Any]:
    """Lower an array. Its FIRST element decides the kind, and an EMPTY array
    lowers to an empty list of strings — both straight from ubCode's
    ``array_to_filter``."""
    if not value:
        return ("list_str", [])
    first = value[0]
    if isinstance(first, bool):
        return ("list_bool", [item for item in value if isinstance(item, bool)])
    if isinstance(first, str):
        return ("list_str", [item for item in value if isinstance(item, str)])
    if isinstance(first, int):
        return (
            "list_int",
            [
                item
                for item in value
                if isinstance(item, int) and not isinstance(item, bool)
            ],
        )
    return ("list_float", [item for item in value if isinstance(item, float)])


def _lower(value: Any) -> tuple[str, Any]:
    """Lower a variant value the way ubCode's ``variant_value_to_filter`` does."""
    if isinstance(value, dict):
        # A mapping is compared by its truthiness, exactly as ubCode does it.
        return ("bool", bool(value))
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value)
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, list):
        return _lower_list(value)
    msg = f"unsupported variant value of type {type(value).__name__}"
    raise VariantEvalError(msg)


def _matches_literal(value: tuple[str, Any], literal: tuple[str, Any]) -> bool:
    """TABLE 2's equality row. Any pair without an arm is ``False``."""
    kind, payload = value
    lkind, lvalue = literal
    if kind == lkind and kind in {"str", "bool", "int", "float", "null"}:
        return bool(payload == lvalue)
    if kind == "int" and lkind == "float":
        return float(payload) == lvalue
    if kind == "float" and lkind == "int":
        return payload == float(lvalue)
    return False


def _as_literal(value: tuple[str, Any], name: str) -> tuple[str, Any]:
    """Convert a field's value into a literal for a field-vs-field equality."""
    kind, _payload = value
    if kind in _LIST_KINDS:
        msg = f"unsupported type for equality check; `{name}` is a list"
        raise VariantEvalError(msg)
    return value


def _compare_number(
    value: tuple[str, Any], other: float, operator_node: ast.cmpop, name: str
) -> bool:
    """TABLE 2's ordering row. A non-numeric left value RAISES."""
    kind, payload = value
    if kind not in _NUMBER_KINDS:
        msg = f"unsupported type for number comparison; `{name}` is a {kind}"
        raise VariantEvalError(msg)
    left = float(payload)
    if isinstance(operator_node, ast.Lt):
        return left < other
    if isinstance(operator_node, ast.LtE):
        return left <= other
    if isinstance(operator_node, ast.Gt):
        return left > other
    return left >= other


def _literal_in_field(
    value: tuple[str, Any], literal: tuple[str, Any], name: str
) -> bool:
    """TABLE 2's ``literal in field`` row."""
    kind, payload = value
    lkind, lvalue = literal
    if kind == "str":
        if lkind != "str":
            msg = f"unsupported literal type for `in` against the string `{name}`"
            raise VariantEvalError(msg)
        return lvalue in payload
    if kind in _LIST_KINDS:
        return _literal_in_list(kind, payload, literal, name)
    msg = f"unsupported type for `in`; `{name}` is a {kind}"
    raise VariantEvalError(msg)


def _literal_in_list(
    kind: str, payload: list[Any], literal: tuple[str, Any], name: str
) -> bool:
    """The list half of TABLE 2's ``literal in field`` row.

    A literal whose type does not match the array's RAISES rather than
    returning ``False`` — `2 in var.tags` is an evaluation error where Python
    would say ``False``.
    """
    lkind, lvalue = literal
    if kind == "list_str" and lkind == "str":
        return lvalue in payload
    if kind == "list_bool" and lkind == "bool":
        return lvalue in payload
    if kind == "list_int":
        if lkind == "int":
            return lvalue in payload
        if lkind == "float":
            return any(float(item) == lvalue for item in payload)
    if kind == "list_float":
        if lkind == "float":
            return lvalue in payload
        if lkind == "int":
            return any(item == float(lvalue) for item in payload)
    msg = f"unsupported literal type for `in` against the list `{name}`"
    raise VariantEvalError(msg)


def _lookup(node: ast.AST, data: dict[str, Any]) -> Any:
    """Resolve a ``var.*`` attribute chain against the merged mapping."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.reverse()
    current: Any = data
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            msg = f"unknown variant data key `var.{'.'.join(walked)}`"
            raise VariantEvalError(msg)
        current = current[part]
    return current


def _transform(node: ast.AST, value: tuple[str, Any], name: str) -> tuple[str, Any]:
    """Apply a ``.upper()`` / ``.lower()`` suffix, raising on a non-string."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return value
    kind, payload = value
    if kind != "str":
        msg = f"unsupported type for `.{node.func.attr}()`; `{name}` is a {kind}"
        raise VariantEvalError(msg)
    return ("str", payload.upper() if node.func.attr == "upper" else payload.lower())


def _receiver_name(node: ast.AST) -> str:
    """The dotted spelling of a receiver's ``var.*`` chain, for a message."""
    chain = _receiver(node)
    return _dotted(chain) if chain is not None else "?"


def _receiver_value(node: ast.AST, data: dict[str, Any]) -> tuple[str, Any]:
    """Resolve and lower a receiver, applying any transformer suffix."""
    chain = _receiver(node)
    if chain is None:  # pragma: no cover - validate() guarantees it
        msg = f"cannot evaluate `{type(node).__name__}`"
        raise VariantEvalError(msg)
    value = _lower(_lookup(chain, data))
    return _transform(node, value, _dotted(chain))


def _evaluate_compare(node: ast.Compare, data: dict[str, Any]) -> bool:
    """Evaluate one comparison through TABLE 2."""
    op = node.ops[0]
    left, right = node.left, node.comparators[0]

    if isinstance(op, _IS_OPS):
        value = _receiver_value(left, data)
        result = value[0] == "null"
        return result if isinstance(op, ast.Is) else not result

    if isinstance(op, _IN_OPS):
        if _receiver(right) is not None:
            container = _receiver_value(right, data)
            literal = (_value_kind(left), _literal_value(left))
            result = _literal_in_field(container, literal, _receiver_name(right))
        else:
            value = _receiver_value(left, data)
            elements = right.elts if isinstance(right, ast.List | ast.Tuple) else []
            result = any(
                _matches_literal(value, (_value_kind(element), _literal_value(element)))
                for element in elements
            )
        return result if isinstance(op, ast.In) else not result

    left_is_receiver = _receiver(left) is not None
    receiver_node = left if left_is_receiver else right
    other_node = right if left_is_receiver else left
    value = _receiver_value(receiver_node, data)
    name = _receiver_name(receiver_node)

    if isinstance(op, _EQ_OPS):
        if _receiver(other_node) is not None:
            other = _as_literal(
                _receiver_value(other_node, data), _receiver_name(other_node)
            )
        else:
            other = (_value_kind(other_node), _literal_value(other_node))
        result = _matches_literal(value, other)
        return result if isinstance(op, ast.Eq) else not result

    # Ordering. `a < b` written the other way round is `b > a`, which is how
    # ubCode canonicalises a Yoda comparison (`literal_cmp_var_field_expr`).
    operator_node: ast.cmpop = op
    if not left_is_receiver:
        operator_node = _FLIPPED[type(op)]()
    if _receiver(other_node) is not None:
        other_value = _receiver_value(other_node, data)
        if other_value[0] not in _NUMBER_KINDS:
            msg = (
                f"unsupported type for number comparison; "
                f"`{_receiver_name(other_node)}` is a {other_value[0]}"
            )
            raise VariantEvalError(msg)
        other_number = float(other_value[1])
    else:
        other_number = float(_literal_value(other_node))
    return _compare_number(value, other_number, operator_node, name)


#: Ordering operators under operand exchange, for a Yoda comparison.
_FLIPPED: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.Gt,
    ast.Gt: ast.Lt,
    ast.LtE: ast.GtE,
    ast.GtE: ast.LtE,
}


def _evaluate_predicate(node: ast.Call, data: dict[str, Any]) -> bool:
    """Evaluate a terminal ``.startswith(…)`` / ``.endswith(…)``."""
    func = node.func
    if not isinstance(func, ast.Attribute):  # pragma: no cover - validated
        msg = "a string predicate may only be called on a `var.*` field"
        raise VariantEvalError(msg)
    receiver = func.value
    value = _receiver_value(receiver, data)
    name = _receiver_name(receiver)
    if value[0] != "str":
        msg = f"unsupported type for a string predicate; `{name}` is a {value[0]}"
        raise VariantEvalError(msg)
    literal = _literal_value(node.args[0])
    if func.attr == "startswith":
        return value[1].startswith(literal)
    return value[1].endswith(literal)


def interpret(node: ast.expr, data: dict[str, Any]) -> bool:
    """Evaluate a validated condition against the merged variant data.

    ``and`` / ``or`` short-circuit left to right, which is what ubCode's DNF
    evaluation does too (measured): an error in an operand that is never
    reached never surfaces.

    The interpreter is a pure function of the validated tree and the data: the
    two questions that need the source text (``-2`` versus ``- 2``, and one
    string literal versus an implicitly concatenated pair) are settled by
    :func:`validate` and cannot be reopened here.

    :param node: The node :func:`validate` returned.
    :param data: The merged variant map — a plain mapping, not a proxy.
    :raises VariantEvalError: On an unknown key or an unsupported type pair.
    """
    try:
        return _interpret(node, data)
    except RecursionError as exc:
        msg = "the condition is nested too deeply to evaluate"
        raise VariantEvalError(msg) from exc


def _interpret(node: ast.AST, data: dict[str, Any]) -> bool:
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_interpret(value, data) for value in node.values)
        return any(_interpret(value, data) for value in node.values)
    if isinstance(node, ast.UnaryOp):
        return not _interpret(node.operand, data)
    if isinstance(node, ast.Compare):
        return _evaluate_compare(node, data)
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.Call):
        return _evaluate_predicate(node, data)
    msg = f"cannot evaluate `{type(node).__name__}`"  # pragma: no cover
    raise VariantEvalError(msg)  # pragma: no cover


def evaluate(expr: str, data: dict[str, Any]) -> bool:
    """Validate and evaluate ``expr`` in one call."""
    return interpret(validate(expr), data)


# ---------------------------------------------------------------------------
# Variant data — a private copy of sphinx-needs' semantics
# ---------------------------------------------------------------------------


def validate_variant_data(data: Any, path: str = "var") -> None:
    """Check that ``data`` has the shape a variant map is allowed to have.

    Keys must be strings; leaves must be ``str`` / ``bool`` / ``int`` /
    ``float``; a list must be empty or uniform-scalar; nested mappings recurse.

    :raises VariantDataError: On any violation, naming the dotted path.
    """
    if not isinstance(data, dict):
        msg = f"{path}: expected a mapping, got {type(data).__name__}"
        raise VariantDataError(msg)
    for key, value in data.items():
        if not isinstance(key, str):
            msg = f"{path}: all keys must be strings, got {type(key).__name__}"
            raise VariantDataError(msg)
        full = f"{path}.{key}"
        if isinstance(value, dict):
            validate_variant_data(value, full)
        elif isinstance(value, list):
            _validate_variant_list(value, full)
        elif not isinstance(value, _SCALAR_TYPES):
            msg = (
                f"{full}: expected str/bool/int/float/list/mapping, "
                f"got {type(value).__name__}"
            )
            raise VariantDataError(msg)


def _validate_variant_list(value: list[Any], full: str) -> None:
    """An array must be empty, or uniform and scalar."""
    if not value:
        return
    first_type = type(value[0])
    if first_type not in _SCALAR_TYPES:
        msg = (
            f"{full}: array elements must be str/bool/int/float, "
            f"got {first_type.__name__}"
        )
        raise VariantDataError(msg)
    for index, item in enumerate(value):
        if type(item) is not first_type:
            msg = (
                f"{full}[{index}]: expected {first_type.__name__}, got "
                f"{type(item).__name__} (arrays must be uniform type)"
            )
            raise VariantDataError(msg)


def load_variant_data_file(path: Path) -> dict[str, Any]:
    """Load a variant-data JSON file and validate its shape.

    JSON only, and the top level must be an object — the same three failures
    sphinx-needs reports (missing file, undecodable JSON, non-object).

    :raises VariantDataError: On any of them.
    """
    if not path.is_file():
        msg = f"variant data file not found: {path}"
        raise VariantDataError(msg)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"invalid JSON in {path}: {exc}"
        raise VariantDataError(msg) from exc
    except OSError as exc:  # pragma: no cover - defensive
        msg = f"could not read {path}: {exc}"
        raise VariantDataError(msg) from exc
    if not isinstance(raw, dict):
        msg = (
            f"variant data file must contain a JSON object, "
            f"got {type(raw).__name__}: {path}"
        )
        raise VariantDataError(msg)
    validate_variant_data(raw)
    return raw


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``override`` into ``base``; ``override`` wins at the leaves.

    Recurses **only when both sides are mappings**. Everything else is a
    wholesale replacement — a list replaces a list entirely, a scalar replaces
    a mapping and vice versa. That is sphinx-needs' rule, reproduced exactly,
    and it is what makes the merge idempotent (see
    :func:`resolve_variant_data`).
    """
    result = base.copy()
    for key, value in override.items():
        existing = result.get(key)
        if key in result and isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


def resolve_variant_data(
    inline: Any,
    file_ref: Path | None,
) -> dict[str, Any]:
    """Compute the merged variant map: file first, inline deep-merged on top.

    The merge is **unconditional**, and that is the whole trick. Three worlds
    have to give the same answer:

    * sphinx-needs absent — nothing else computes the map, so this is the whole
      computation;
    * sphinx-needs installed but not yet resolving at ``config-inited``
      (every release up to and including 8.3.1) — ``needs_variant_data`` holds
      the *inline* half only, and this supplies the merge it has not performed;
    * sphinx-needs resolving at ``config-inited`` (post-#1787) —
      ``needs_variant_data`` is already merged, and re-merging it is a no-op,
      because ``deep_merge(file, already_merged) == already_merged`` for every
      shape ``deep_merge`` can produce.

    So there is no version sniffing, no import of sphinx-needs and no feature
    detection, and the answer always agrees with whatever sphinx-needs computed.
    ``tests/test_variant_data.py`` pins all three cells plus the idempotency.

    :param inline: The inline mapping (``needs_variant_data`` or the TOML's
        ``[needs.variant_data]`` table). ``None`` and ``{}`` both mean "none".
    :param file_ref: An **already anchored** absolute path, or ``None``. The
        two anchors are the caller's business — see
        :func:`sphinx_mounts.config.load_variant_sources_from_toml`.
    :raises VariantDataError: If the file or the inline mapping is malformed.
    """
    base: dict[str, Any] = {}
    if file_ref is not None:
        base = load_variant_data_file(file_ref)
    if inline:
        validate_variant_data(inline)
    return deep_merge(base, inline or {})
