"""Human-readable previews and syntax guidance for FCSTM formulas."""

from dataclasses import dataclass
from html import escape
from typing import Tuple

from pyfcstm.dsl import parse_with_grammar_entry
from pyfcstm.model import parse_expr_from_string

from .formulas import FormulaKind


@dataclass(frozen=True)
class FormulaKindDescription:
    title: str
    source_label: str
    preview_label: str
    placeholder: str
    syntax_summary: str
    examples: Tuple[str, ...]


@dataclass(frozen=True)
class FormulaRenderResult:
    kind: FormulaKind
    html: str
    plain_text: str


_DESCRIPTIONS = {
    FormulaKind.LOGICAL: FormulaKindDescription(
        title="编辑逻辑公式",
        source_label="FCSTM 逻辑公式",
        preview_label="渲染结果",
        placeholder="例如：count >= 1 && enabled",
        syntax_summary=(
            "比较：&lt;、&lt;=、&gt;、&gt;=、==、!=；逻辑：and/&&、or/||、"
            "not/!、xor、implies/=&gt;、iff；布尔值：true、false。"
        ),
        examples=(
            "count >= 1 && enabled != 0",
            "not (failed != 0) || retry < 3",
            "(count > 0) ? true : false",
        ),
    ),
    FormulaKind.NUMERIC: FormulaKindDescription(
        title="编辑数值公式",
        source_label="FCSTM 数值公式",
        preview_label="渲染结果",
        placeholder="例如：sqrt(x ** 2 + y ** 2)",
        syntax_summary=(
            "运算：+、-、*、/、%、**、&lt;&lt;、&gt;&gt;、&amp;、^、|；常量："
            "pi、E、tau；函数：sin/cos/tan、反三角与双曲函数、sqrt/cbrt、"
            "exp、log/log10/log2/log1p、abs、ceil、floor、round、trunc、sign。"
        ),
        examples=(
            "x * 2 + 1",
            "sqrt(x ** 2 + y ** 2)",
            "abs(error) + round(offset)",
        ),
    ),
    FormulaKind.EFFECT: FormulaKindDescription(
        title="编辑迁移动作",
        source_label="FCSTM 迁移动作",
        preview_label="动作结构",
        placeholder="例如：count = count + 1;",
        syntax_summary=(
            "赋值：变量 = 数值公式;。分支：if [逻辑公式] { ... }，可继续使用 "
            "else if [...] { ... } 和 else { ... }。每条赋值必须以分号结束。"
        ),
        examples=(
            "count = count + 1;",
            "if [count >= 10] {\n    count = 0;\n}",
            (
                "if [enabled != 0] {\n    count = count + 1;\n} else {\n"
                "    count = 0;\n}"
            ),
        ),
    ),
    FormulaKind.LIFECYCLE: FormulaKindDescription(
        title="编辑生命周期动作",
        source_label="FCSTM 生命周期动作",
        preview_label="动作结构",
        placeholder="例如：counter = counter + 1;",
        syntax_summary=(
            "生命周期动作与迁移动作使用同一操作语法：赋值语句以及 "
            "if / else if / else 分支；条件使用方括号，每条赋值以分号结束。"
        ),
        examples=(
            "counter = counter + 1;",
            "if [counter > limit] {\n    counter = 0;\n}",
            "active = active + 1;\nelapsed = elapsed + step;",
        ),
    ),
}


_OPERATOR_SYMBOLS = {
    "*": "×",
    "/": "÷",
    "**": "^",
    "<=": "≤",
    ">=": "≥",
    "==": "=",
    "!=": "≠",
    "&&": "∧",
    "and": "∧",
    "||": "∨",
    "or": "∨",
    "xor": "⊕",
    "=>": "⇒",
    "implies": "⇒",
    "iff": "⇔",
    "<<": "≪",
    ">>": "≫",
}


def formula_kind_description(kind) -> FormulaKindDescription:
    return _DESCRIPTIONS[FormulaKind(kind)]


class FormulaRenderService:
    """Render parser-backed previews without interpreting user expressions."""

    def render(self, kind, text) -> FormulaRenderResult:
        kind = FormulaKind(kind)
        source = text.strip()
        if kind in (FormulaKind.LOGICAL, FormulaKind.NUMERIC):
            node = parse_expr_from_string(source, mode=kind.value)
            body = self._render_expression(node)
            plain_text = str(node)
        else:
            statements = parse_with_grammar_entry(
                source, "operational_statement_set"
            )
            body = self._render_statements(statements)
            plain_text = source
        html = (
            "<div style='font-size:16px; color:#172033; padding:10px;'>"
            + body
            + "</div>"
        )
        return FormulaRenderResult(kind=kind, html=html, plain_text=plain_text)

    @classmethod
    def _render_expression(cls, node):
        name = type(node).__name__
        if name in ("Variable", "Name"):
            return "<i>{}</i>".format(escape(str(getattr(node, "name"))))
        if name in ("Integer", "HexInt", "Float"):
            value = getattr(node, "raw", getattr(node, "value", node))
            return escape(str(value))
        if name == "Boolean":
            value = getattr(node, "value", getattr(node, "raw", False))
            truth = value is True or str(value).lower() == "true"
            return "<b>{}</b>".format("true" if truth else "false")
        if name in ("Constant", "MathConst"):
            raw = str(node)
            return {"pi": "π", "E": "e", "tau": "τ"}.get(raw, escape(raw))
        if name in ("Paren", "Parenthesized"):
            value = getattr(node, "expr", getattr(node, "x", node))
            return "({})".format(cls._render_expression(value))
        if name == "UFunc":
            func = str(getattr(node, "func"))
            value = getattr(node, "x", getattr(node, "expr", None))
            rendered = cls._render_expression(value)
            if func == "sqrt":
                return "√<span style='text-decoration:overline'>{}</span>".format(
                    rendered
                )
            if func == "cbrt":
                return "∛<span style='text-decoration:overline'>{}</span>".format(
                    rendered
                )
            if func == "abs":
                return "|{}|".format(rendered)
            return "{}({})".format(escape(func), rendered)
        if name == "UnaryOp":
            op = str(getattr(node, "op"))
            value = getattr(node, "x", getattr(node, "expr", None))
            symbol = "¬" if op in ("!", "not") else escape(op)
            return "{}{}".format(symbol, cls._render_expression(value))
        if name == "BinaryOp":
            left = getattr(node, "x", getattr(node, "expr1", None))
            right = getattr(node, "y", getattr(node, "expr2", None))
            op = str(getattr(node, "op"))
            left_html = cls._render_expression(left)
            right_html = cls._render_expression(right)
            if op == "**":
                return "({}<sup>{}</sup>)".format(left_html, right_html)
            symbol = _OPERATOR_SYMBOLS.get(op, escape(op))
            return "({} <b>{}</b> {})".format(left_html, symbol, right_html)
        if name == "ConditionalOp":
            condition = cls._render_expression(getattr(node, "cond"))
            true_value = cls._render_expression(getattr(node, "if_true"))
            false_value = cls._render_expression(getattr(node, "if_false"))
            return (
                "<span>{}，当 {}；否则 {}</span>".format(
                    true_value, condition, false_value
                )
            )
        return "<code>{}</code>".format(escape(str(node)))

    @classmethod
    def _render_statements(cls, statements):
        rows = []
        for statement in statements:
            rows.append(cls._render_statement(statement))
        if not rows:
            return "<span style='color:#687386'>（无动作）</span>"
        return "<div>{}</div>".format("".join(rows))

    @classmethod
    def _render_statement(cls, statement):
        name = type(statement).__name__
        if name == "OperationAssignment":
            target = escape(str(getattr(statement, "name")))
            expression = cls._render_expression(getattr(statement, "expr"))
            return (
                "<div style='margin:5px 0;'><i>{}</i> "
                "<b style='color:#2457a7'>←</b> {}</div>"
            ).format(target, expression)
        if name == "OperationIf":
            blocks = []
            for index, branch in enumerate(getattr(statement, "branches", ())):
                condition = getattr(branch, "condition", None)
                if condition is None:
                    heading = "否则"
                elif index == 0:
                    heading = "如果 {}".format(cls._render_expression(condition))
                else:
                    heading = "否则如果 {}".format(
                        cls._render_expression(condition)
                    )
                nested = cls._render_statements(getattr(branch, "statements", ()))
                blocks.append(
                    "<div style='margin:6px 0 6px 12px; border-left:3px solid #9bb7e8; "
                    "padding-left:10px;'><b>{}</b>{}</div>".format(heading, nested)
                )
            return "".join(blocks)
        return "<div><code>{}</code></div>".format(escape(str(statement)))


__all__ = [
    "FormulaKindDescription",
    "FormulaRenderResult",
    "FormulaRenderService",
    "formula_kind_description",
]
