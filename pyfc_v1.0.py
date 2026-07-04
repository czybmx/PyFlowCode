#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyFlowCode — 节点式 Python 代码可视化编辑器 (单文件版)
================================================================
像 ComfyUI 一样，通过拖拽节点和连线编写 Python 代码。
所见即所得的可视化编程，一键导出标准 .py 文件。

运行方式:
    python run.py

依赖:
    PySide6 (若未安装会自动安装)

功能:
    - 38 个内置节点 (字面量/运算/比较/逻辑/容器/字符串/控制流/函数/IO/模块)
    - 无限画布 (平移/缩放/拖拽节点/端口连线)
    - 端口类型颜色标识 + 类型兼容性检查
    - 子图节点 (双击进入函数体编辑)
    - Python 解释器 (直接运行查看结果)
    - Python 代码生成器 (一键导出 .py 文件)
    - 工作流文件导入/导出 (.pyflow JSON)
    - 5 个预置示例
"""

# ============================================================================
# 自动安装 PySide6
# ============================================================================

import sys
import subprocess

def _ensure_pyside6():
    try:
        import PySide6  # noqa
        return True
    except ImportError:
        print("PySide6 未安装，正在自动安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "PySide6"])
            return True
        except Exception as e:
            print(f"自动安装失败: {e}")
            print("请手动安装: pip install PySide6")
            return False

if not _ensure_pyside6():
    sys.exit(1)

# ============================================================================
# 导入
# ============================================================================

import os
import json
import time
import math
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import (
    Qt, QPointF, QRectF, QSizeF, Signal, QObject,
    QEvent, QTimer, QSize,
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QAction,
    QPainterPath, QPainterPathStroker, QCursor, QKeySequence, QShortcut,
    QLinearGradient, QPixmap, QFontMetrics,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPathItem,
    QGraphicsTextItem, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QToolBar, QStatusBar, QSplitter, QFrame, QScrollArea, QFormLayout,
    QFileDialog, QMessageBox, QInputDialog, QMenu, QSizePolicy,
    QDialog, QTextEdit, QStyledItemDelegate,
)

# ============================================================================
# 类型系统
# ============================================================================

PYTYPE_COLORS = {
    "int":      "#3b82f6",
    "float":    "#06b6d4",
    "bool":     "#a855f7",
    "str":      "#22c55e",
    "bytes":    "#65a30d",
    "list":     "#f59e0b",
    "dict":     "#ef4444",
    "tuple":    "#f97316",
    "set":      "#eab308",
    "range":    "#14b8a6",
    "callable": "#ec4899",
    "module":   "#64748b",
    "none":     "#94a3b8",
    "any":      "#e4e4e7",
}

def get_type_color(t):
    return PYTYPE_COLORS.get(t, "#94a3b8")

def is_type_compatible(from_t, to_t):
    if from_t == "any" or to_t == "any":
        return True
    if from_t == to_t:
        return True
    if from_t == "int" and to_t == "float":
        return True
    if from_t == "bool" and to_t in ("int", "float"):
        return True
    if from_t == "int" and to_t == "bool":
        return True
    return False

def py_repr(v):
    """将 Python 值转为代码字面量字符串"""
    if v is None:
        return "None"
    if v is True:
        return "True"
    if v is False:
        return "False"
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(py_repr(x) for x in v) + "]"
    if isinstance(v, tuple):
        if len(v) == 1:
            return "(" + py_repr(v[0]) + ",)"
        return "(" + ", ".join(py_repr(x) for x in v) + ")"
    if isinstance(v, set):
        if not v:
            return "set()"
        return "{" + ", ".join(py_repr(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{py_repr(k)}: {py_repr(val)}" for k, val in v.items()) + "}"
    if isinstance(v, range):
        if v.step == 1:
            if v.start == 0:
                return f"range({v.stop})"
            return f"range({v.start}, {v.stop})"
        return f"range({v.start}, {v.stop}, {v.step})"
    return repr(v)

def py_str(v):
    """将 Python 值转为可读字符串 (print 输出)"""
    if v is None:
        return "None"
    if v is True:
        return "True"
    if v is False:
        return "False"
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple, set, dict, range)):
        return py_repr(v)
    if isinstance(v, PyClosure):
        return f"<function {v.name}>"
    if isinstance(v, PyModule):
        return f"<module '{v.name}'>"
    return str(v)

# ============================================================================
# 闭包 / 模块
# ============================================================================

class PyClosure:
    """函数闭包 — 由 DefineFunc 节点产生"""
    def __init__(self, name, params, body_nodes, body_edges, return_node_id, captured_scope=None):
        self.name = name
        self.params = params          # 参数名列表
        self.body_nodes = body_nodes  # 函数体子图节点
        self.body_edges = body_edges  # 函数体子图连线
        self.return_node_id = return_node_id
        self.captured_scope = captured_scope or {}
        self.define_node_id = None    # 关联的 DefineFunc 节点 ID

class PyModule:
    """模块标记"""
    def __init__(self, name):
        self.name = name

# ============================================================================
# 节点注册表
# ============================================================================

CATEGORY_LABELS = {
    "literal":    "字面量",
    "operator":   "算术运算",
    "comparison": "比较",
    "logic":      "逻辑",
    "container":  "容器",
    "string":     "字符串",
    "control":    "控制流",
    "function":   "函数",
    "io":         "输入输出",
    "module":     "模块",
}

CATEGORY_ICONS = {
    "literal":    "🔢",
    "operator":   "➕",
    "comparison": "⚖️",
    "logic":      "🧠",
    "container":  "📦",
    "string":     "📝",
    "control":    "🔀",
    "function":   "⚙️",
    "io":         "🖨️",
    "module":     "📚",
}

NODE_REGISTRY = {}

def register_node(defn):
    NODE_REGISTRY[defn["type"]] = defn

def get_node_def(type_id):
    return NODE_REGISTRY.get(type_id)

def list_nodes_by_category():
    result = {cat: [] for cat in CATEGORY_LABELS}
    for defn in NODE_REGISTRY.values():
        result[defn["category"]].append(defn)
    return result

# ============================================================================
# 内置节点
# ============================================================================

def _make_binary_op(type_id, label, op_str, op_func, result_type="any"):
    return {
        "type": type_id,
        "label": label,
        "category": "operator",
        "inputs": [
            {"id": "a", "label": "a", "type": "any", "default": 0},
            {"id": "b", "label": "b", "type": "any", "default": 0},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": result_type}],
        "execute": lambda ctx, inp: {"result": op_func(inp["a"], inp["b"])},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"({inp['a']} {op_str} {inp['b']})"}},
    }

def _make_comparison(type_id, label, op_str, op_func):
    return {
        "type": type_id,
        "label": label,
        "category": "comparison",
        "inputs": [
            {"id": "a", "label": "a", "type": "any", "default": 0},
            {"id": "b", "label": "b", "type": "any", "default": 0},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "bool"}],
        "execute": lambda ctx, inp: {"result": op_func(inp["a"], inp["b"])},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"({inp['a']} {op_str} {inp['b']})"}},
    }

def register_builtin_nodes():
    # --- 字面量 ---
    for tid, lbl, ptype, pdefault in [
        ("literal_int",   "整数",   "int",   0),
        ("literal_float", "浮点数", "float", 0.0),
        ("literal_str",   "字符串", "str",   ""),
        ("literal_bool",  "布尔值", "bool",  True),
    ]:
        register_node({
            "type": tid,
            "label": lbl,
            "category": "literal",
            "inputs": [],
            "outputs": [{"id": "value", "label": "值", "type": ptype, "editable": True}],
            "execute": lambda ctx, inp, d=pdefault: {"value": d},
            "to_code": None,  # 特殊处理
            "_literal_type": ptype,
        })

    register_node({
        "type": "literal_none",
        "label": "None",
        "category": "literal",
        "inputs": [],
        "outputs": [{"id": "value", "label": "值", "type": "none"}],
        "execute": lambda ctx, inp: {"value": None},
        "to_code": lambda ctx, inp: {"assignments": {"value": "None"}},
    })

    # --- 算术运算 ---
    register_node(_make_binary_op("op_add", "加法 (a + b)", "+",
        lambda a, b: (a + b) if not (isinstance(a, str) or isinstance(b, str)) else (py_str(a) + py_str(b))))
    register_node(_make_binary_op("op_sub", "减法 (a - b)", "-",
        lambda a, b: a - b))
    register_node(_make_binary_op("op_mul", "乘法 (a * b)", "*",
        lambda a, b: (a * b) if not (isinstance(a, str) and isinstance(b, int)) else a * b))
    register_node(_make_binary_op("op_div", "除法 (a / b)", "/",
        lambda a, b: a / b, "float"))
    register_node(_make_binary_op("op_floordiv", "整除 (a // b)", "//",
        lambda a, b: a // b))
    register_node(_make_binary_op("op_mod", "取余 (a % b)", "%",
        lambda a, b: a % b))
    register_node(_make_binary_op("op_pow", "幂 (a ** b)", "**",
        lambda a, b: a ** b))

    register_node({
        "type": "op_neg",
        "label": "负号 (-a)",
        "category": "operator",
        "inputs": [{"id": "a", "label": "a", "type": "any", "default": 0}],
        "outputs": [{"id": "result", "label": "结果", "type": "any"}],
        "execute": lambda ctx, inp: {"result": -inp["a"]},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"(-{inp['a']})"}},
    })

    # --- 比较 ---
    register_node(_make_comparison("cmp_eq", "等于 (a == b)", "==", lambda a, b: a == b))
    register_node(_make_comparison("cmp_ne", "不等于 (a != b)", "!=", lambda a, b: a != b))
    register_node(_make_comparison("cmp_gt", "大于 (a > b)", ">", lambda a, b: a > b))
    register_node(_make_comparison("cmp_lt", "小于 (a < b)", "<", lambda a, b: a < b))
    register_node(_make_comparison("cmp_ge", "大于等于 (a >= b)", ">=", lambda a, b: a >= b))
    register_node(_make_comparison("cmp_le", "小于等于 (a <= b)", "<=", lambda a, b: a <= b))

    # --- 逻辑 ---
    register_node({
        "type": "logic_and",
        "label": "与 (a and b)",
        "category": "logic",
        "inputs": [
            {"id": "a", "label": "a", "type": "bool", "default": True},
            {"id": "b", "label": "b", "type": "bool", "default": True},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "bool"}],
        "execute": lambda ctx, inp: {"result": bool(inp["a"]) and bool(inp["b"])},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"({inp['a']} and {inp['b']})"}},
    })
    register_node({
        "type": "logic_or",
        "label": "或 (a or b)",
        "category": "logic",
        "inputs": [
            {"id": "a", "label": "a", "type": "bool", "default": False},
            {"id": "b", "label": "b", "type": "bool", "default": False},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "bool"}],
        "execute": lambda ctx, inp: {"result": bool(inp["a"]) or bool(inp["b"])},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"({inp['a']} or {inp['b']})"}},
    })
    register_node({
        "type": "logic_not",
        "label": "非 (not a)",
        "category": "logic",
        "inputs": [{"id": "a", "label": "a", "type": "bool", "default": False}],
        "outputs": [{"id": "result", "label": "结果", "type": "bool"}],
        "execute": lambda ctx, inp: {"result": not inp["a"]},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"(not {inp['a']})"}},
    })

    # --- 容器 ---
    register_node({
        "type": "list_make",
        "label": "构造列表",
        "category": "container",
        "inputs": [
            {"id": "item0", "label": "元素 0", "type": "any"},
            {"id": "item1", "label": "元素 1", "type": "any"},
            {"id": "item2", "label": "元素 2", "type": "any"},
        ],
        "outputs": [{"id": "list", "label": "列表", "type": "list"}],
        "execute": lambda ctx, inp: {"list": [inp.get(k) for k in ["item0","item1","item2"] if inp.get(k) is not None]},
        "to_code": lambda ctx, inp: {"assignments": {"list": f"[{', '.join(inp.get(k,'None') for k in ['item0','item1','item2'])}]"}},
    })
    register_node({
        "type": "list_length",
        "label": "长度 (len)",
        "category": "container",
        "inputs": [{"id": "obj", "label": "对象", "type": "any", "default": []}],
        "outputs": [{"id": "length", "label": "长度", "type": "int"}],
        "execute": lambda ctx, inp: {"length": len(inp["obj"]) if inp["obj"] is not None else 0},
        "to_code": lambda ctx, inp: {"assignments": {"length": f"len({inp['obj']})"}},
    })
    register_node({
        "type": "list_index",
        "label": "索引 (obj[i])",
        "category": "container",
        "inputs": [
            {"id": "obj", "label": "对象", "type": "any", "default": []},
            {"id": "index", "label": "索引", "type": "int", "default": 0},
        ],
        "outputs": [{"id": "value", "label": "元素", "type": "any"}],
        "execute": lambda ctx, inp: {"value": (inp["obj"][inp["index"]] if inp["obj"] is not None and len(inp["obj"]) > inp["index"] else None)},
        "to_code": lambda ctx, inp: {"assignments": {"value": f"{inp['obj']}[{inp['index']}]"}},
    })
    register_node({
        "type": "list_append",
        "label": "追加 (append)",
        "category": "container",
        "inputs": [
            {"id": "list", "label": "列表", "type": "list", "default": []},
            {"id": "item", "label": "元素", "type": "any"},
        ],
        "outputs": [{"id": "result", "label": "新列表", "type": "list"}],
        "execute": lambda ctx, inp: {"result": list(inp.get("list") or []) + [inp.get("item")]},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"({inp['list']} + [{inp['item']}])"}},
    })
    register_node({
        "type": "range_node",
        "label": "range(start, stop)",
        "category": "container",
        "inputs": [
            {"id": "start", "label": "start", "type": "int", "default": 0},
            {"id": "stop",  "label": "stop",  "type": "int", "default": 10},
            {"id": "step",  "label": "step",  "type": "int", "default": 1},
        ],
        "outputs": [{"id": "range", "label": "range", "type": "range"}],
        "execute": lambda ctx, inp: {"range": range(inp["start"], inp["stop"], inp["step"])},
        "to_code": lambda ctx, inp: {"assignments": {"range": f"range({inp['start']}, {inp['stop']}, {inp['step']})"}},
    })

    # --- 字符串 ---
    register_node({
        "type": "str_format",
        "label": "字符串格式化 (f-string)",
        "category": "string",
        "inputs": [
            {"id": "template", "label": "模板", "type": "str", "default": "Hello, {0}!", "editable": True},
            {"id": "arg0", "label": "参数 0", "type": "any"},
            {"id": "arg1", "label": "参数 1", "type": "any"},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "str"}],
        "execute": lambda ctx, inp: {"result": inp["template"].replace("{0}", py_str(inp.get("arg0"))).replace("{1}", py_str(inp.get("arg1")))},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"{inp['template']}.format({', '.join(inp.get(k,'') for k in ['arg0','arg1'] if inp.get(k))})"}},
    })
    register_node({
        "type": "str_concat",
        "label": "字符串拼接",
        "category": "string",
        "inputs": [
            {"id": "a", "label": "a", "type": "str", "default": ""},
            {"id": "b", "label": "b", "type": "str", "default": ""},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "str"}],
        "execute": lambda ctx, inp: {"result": py_str(inp["a"]) + py_str(inp["b"])},
        "to_code": lambda ctx, inp: {"assignments": {"result": f"({inp['a']} + {inp['b']})"}},
    })

    # --- 控制流 ---
    register_node({
        "type": "control_if",
        "label": "条件选择 (If)",
        "category": "control",
        "isControlFlow": True,
        "inputs": [
            {"id": "condition",   "label": "条件",  "type": "bool", "default": True},
            {"id": "true_value",  "label": "真值",  "type": "any"},
            {"id": "false_value", "label": "假值",  "type": "any"},
        ],
        "outputs": [{"id": "selected", "label": "选中值", "type": "any"}],
        "execute": lambda ctx, inp: {"selected": inp["true_value"] if inp["condition"] else inp["false_value"]},
        "to_code": lambda ctx, inp: {"assignments": {"selected": f"({inp['true_value']} if {inp['condition']} else {inp['false_value']})"}},
    })
    register_node({
        "type": "control_for_each",
        "label": "遍历 (For Each)",
        "category": "control",
        "isControlFlow": True,
        "inputs": [{"id": "iterable", "label": "可迭代", "type": "any", "default": []}],
        "outputs": [
            {"id": "items", "label": "元素列表", "type": "list"},
            {"id": "count", "label": "数量",     "type": "int"},
        ],
        "execute": lambda ctx, inp: {"items": list(inp["iterable"]) if inp["iterable"] is not None else [], "count": len(list(inp["iterable"])) if inp["iterable"] is not None else 0},
        "to_code": lambda ctx, inp: {"assignments": {"items": f"list({inp['iterable']})", "count": f"len({inp['iterable']})"}},
    })
    register_node({
        "type": "control_filter",
        "label": "过滤 (Filter)",
        "category": "control",
        "isControlFlow": True,
        "inputs": [
            {"id": "iterable", "label": "列表",     "type": "list", "default": []},
            {"id": "func",     "label": "过滤函数", "type": "callable"},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "list"}],
        "execute": None,  # 特殊处理
        "to_code": lambda ctx, inp: {"assignments": {"result": f"list(filter({inp['func']}, {inp['iterable']}))"}},
    })
    register_node({
        "type": "control_map",
        "label": "映射 (Map)",
        "category": "control",
        "isControlFlow": True,
        "inputs": [
            {"id": "iterable", "label": "列表",     "type": "list", "default": []},
            {"id": "func",     "label": "映射函数", "type": "callable"},
        ],
        "outputs": [{"id": "result", "label": "结果", "type": "list"}],
        "execute": None,  # 特殊处理
        "to_code": lambda ctx, inp: {"assignments": {"result": f"list(map({inp['func']}, {inp['iterable']}))"}},
    })

    # --- 函数 ---
    register_node({
        "type": "func_define",
        "label": "定义函数 (def)",
        "category": "function",
        "isSubgraph": True,
        "inputs": [
            {"id": "param0", "label": "参数 0", "type": "any"},
            {"id": "param1", "label": "参数 1", "type": "any"},
        ],
        "outputs": [{"id": "func", "label": "函数", "type": "callable"}],
        "execute": None,  # 特殊处理
        "to_code": None,   # 特殊处理
    })
    register_node({
        "type": "func_call",
        "label": "调用函数 (call)",
        "category": "function",
        "inputs": [
            {"id": "func", "label": "函数",    "type": "callable"},
            {"id": "arg0", "label": "参数 0", "type": "any"},
            {"id": "arg1", "label": "参数 1", "type": "any"},
        ],
        "outputs": [{"id": "return", "label": "返回值", "type": "any"}],
        "execute": None,  # 特殊处理
        "to_code": lambda ctx, inp: {"assignments": {"return": f"{inp['func']}({', '.join(inp.get(k,'') for k in ['arg0','arg1'] if inp.get(k))})"}},
    })
    register_node({
        "type": "func_return",
        "label": "返回值 (return)",
        "category": "function",
        "inputs": [{"id": "value", "label": "值", "type": "any"}],
        "outputs": [],
        "execute": lambda ctx, inp: {"value": inp["value"]},
        "to_code": lambda ctx, inp: {"assignments": {}, "statements": [f"return {inp.get('value', 'None')}"]},
    })

    # --- IO ---
    register_node({
        "type": "io_print",
        "label": "打印 (print)",
        "category": "io",
        "inputs": [{"id": "value", "label": "值", "type": "any"}],
        "outputs": [],
        "execute": lambda ctx, inp: (ctx["log"](inp["value"]), {})[1],
        "to_code": lambda ctx, inp: {"assignments": {}, "statements": [f"print({inp.get('value', 'None')})"]},
    })

    # --- 模块 ---
    register_node({
        "type": "module_import",
        "label": "导入模块 (import)",
        "category": "module",
        "inputs": [],
        "outputs": [{"id": "module", "label": "模块", "type": "module"}],
        "execute": lambda ctx, inp: {"module": PyModule("math")},
        "to_code": lambda ctx, inp: {"assignments": {"module": "math"}, "statements": []},
    })

def _fstring_code(inp):
    template = inp.get("template", "")
    args = [inp.get("arg0"), inp.get("arg1")]
    def replacer(m):
        idx = int(m.group(1))
        return "{" + (args[idx] if idx < len(args) and args[idx] else "''") + "}"
    import re
    expr = re.sub(r"\{(\d+)\}", replacer, template)
    return f"f{repr(expr)}"

# ============================================================================
# 解释器
# ============================================================================

def topological_sort(nodes, edges):
    """Kahn 拓扑排序"""
    node_map = {n["id"]: n for n in nodes}
    in_degree = {n["id"]: 0 for n in nodes}
    out_edges_map = {n["id"]: [] for n in nodes}

    for edge in edges:
        if edge["from"] not in node_map or edge["to"] not in node_map:
            continue
        in_degree[edge["to"]] = in_degree.get(edge["to"], 0) + 1
        out_edges_map[edge["from"]].append(edge["to"])

    queue = [nid for nid, d in in_degree.items() if d == 0]
    sorted_nodes = []
    while queue:
        nid = queue.pop(0)
        if nid in node_map:
            sorted_nodes.append(node_map[nid])
        for nxt in out_edges_map.get(nid, []):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    # 把循环依赖中的节点也加进去
    for n in nodes:
        if n not in sorted_nodes:
            sorted_nodes.append(n)
    return sorted_nodes


class Interpreter:
    def __init__(self, all_nodes, all_edges, log_callback, max_depth=50, max_iterations=10000):
        self.all_nodes = all_nodes
        self.all_edges = all_edges
        self.log = log_callback
        self.max_depth = max_depth
        self.max_iterations = max_iterations
        self.outputs = {}       # node_id -> {port_id: value}
        self.errors = []
        self.execution_order = []

    def run(self):
        sorted_nodes = topological_sort(self.all_nodes, self.all_edges)
        for node in sorted_nodes:
            self.execution_order.append(node["id"])
            try:
                node["_runtime"] = {"status": "running"}
                outputs = self._execute_node(node, self.all_nodes, self.all_edges, depth=0, call_stack=set())
                self.outputs[node["id"]] = outputs
                node["_runtime"] = {"outputs": outputs, "status": "ok"}
            except Exception as e:
                msg = str(e)
                self.errors.append({"nodeId": node["id"], "message": msg})
                self.outputs[node["id"]] = {}
                node["_runtime"] = {"error": msg, "status": "error"}
        return self

    def _get_inputs(self, node, nodes, edges):
        defn = get_node_def(node["type"])
        if not defn:
            return {}
        inputs = {}
        for port in defn["inputs"]:
            incoming = None
            for e in edges:
                if e["to"] == node["id"] and e["toPort"] == port["id"]:
                    incoming = e
                    break
            if incoming:
                src = self.outputs.get(incoming["from"], {})
                inputs[port["id"]] = src.get(incoming["fromPort"], port.get("default"))
            else:
                if port["id"] in node.get("params", {}):
                    inputs[port["id"]] = node["params"][port["id"]]
                else:
                    inputs[port["id"]] = port.get("default")
        return inputs

    def _execute_node(self, node, nodes, edges, depth, call_stack):
        defn = get_node_def(node["type"])
        if not defn:
            raise Exception(f"未知节点类型: {node['type']}")

        inputs = self._get_inputs(node, nodes, edges)
        ctx = {
            "log": self.log,
            "scope": {},
            "depth": depth,
        }

        ntype = node["type"]

        # 字面量
        if ntype in ("literal_int", "literal_float", "literal_str", "literal_bool"):
            return {"value": node.get("params", {}).get("value", defn["outputs"][0].get("default"))}

        # 定义函数
        if ntype == "func_define":
            return self._execute_define_func(node, ctx, depth)

        # 调用函数
        if ntype == "func_call":
            return self._execute_call(node, inputs, ctx, depth, call_stack)

        # 过滤
        if ntype == "control_filter":
            return self._execute_filter_map(node, inputs, ctx, depth, call_stack, is_map=False)

        # 映射
        if ntype == "control_map":
            return self._execute_filter_map(node, inputs, ctx, depth, call_stack, is_map=True)

        # 返回值
        if ntype == "func_return":
            return {"value": inputs["value"]}

        # 通用执行
        if defn["execute"]:
            return defn["execute"](ctx, inputs)
        return {}

    def _execute_define_func(self, node, ctx, depth):
        sub = node.get("subgraph") or {"nodes": [], "edges": []}
        defn = get_node_def(node["type"])
        params = [p["id"] for p in defn["inputs"]]

        return_node = None
        for sn in sub["nodes"]:
            if sn["type"] == "func_return":
                return_node = sn
                break

        closure = PyClosure(
            name=node.get("title") or "anonymous",
            params=params,
            body_nodes=sub["nodes"],
            body_edges=sub["edges"],
            return_node_id=return_node["id"] if return_node else None,
            captured_scope=dict(ctx.get("scope", {})),
        )
        closure.define_node_id = node["id"]
        return {"func": closure}

    def _execute_call(self, node, inputs, ctx, depth, call_stack):
        func = inputs.get("func")
        if not isinstance(func, PyClosure):
            raise Exception("Call 节点的 func 输入不是可调用对象")

        if depth >= self.max_depth:
            raise Exception(f"达到最大调用深度 {self.max_depth}，可能存在无限递归")

        if node["id"] in call_stack:
            raise Exception(f"检测到递归调用循环 (节点 {node['id']})")

        # 在子图中执行
        param_values = {}
        for i, p in enumerate(func.params):
            param_values[p] = inputs.get(f"arg{i}")

        return self._exec_subgraph(func, param_values, ctx, depth, call_stack | {node["id"]})

    def _exec_subgraph(self, closure, param_values, ctx, depth, call_stack):
        sub_nodes = closure.body_nodes
        sub_edges = closure.body_edges
        sorted_nodes = topological_sort(sub_nodes, sub_edges)

        sub_outputs = {}
        return_value = None

        sub_ctx = {
            "log": self.log,
            "scope": {**closure.captured_scope, **param_values},
            "depth": depth + 1,
        }

        for sn in sorted_nodes:
            try:
                defn = get_node_def(sn["type"])
                if not defn:
                    continue

                sub_inputs = {}
                for port in defn["inputs"]:
                    incoming = None
                    for e in sub_edges:
                        if e["to"] == sn["id"] and e["toPort"] == port["id"]:
                            incoming = e
                            break
                    if incoming:
                        src = sub_outputs.get(incoming["from"], {})
                        sub_inputs[port["id"]] = src.get(incoming["fromPort"], port.get("default"))
                    elif port["id"] in param_values:
                        sub_inputs[port["id"]] = param_values[port["id"]]
                    elif port["id"] in sn.get("params", {}):
                        sub_inputs[port["id"]] = sn["params"][port["id"]]
                    else:
                        sub_inputs[port["id"]] = port.get("default")

                ntype = sn["type"]
                if ntype in ("literal_int", "literal_float", "literal_str", "literal_bool"):
                    sub_outputs[sn["id"]] = {"value": sn.get("params", {}).get("value", None)}
                    continue

                if ntype == "func_return":
                    return_value = sub_inputs.get("value")
                    sub_outputs[sn["id"]] = {"value": sub_inputs.get("value")}
                    continue

                if ntype == "func_call":
                    r = self._execute_call(sn, sub_inputs, sub_ctx, depth + 1, call_stack)
                    sub_outputs[sn["id"]] = r
                    continue

                if ntype == "control_filter":
                    r = self._execute_filter_map(sn, sub_inputs, sub_ctx, depth + 1, call_stack, is_map=False)
                    sub_outputs[sn["id"]] = r
                    continue

                if ntype == "control_map":
                    r = self._execute_filter_map(sn, sub_inputs, sub_ctx, depth + 1, call_stack, is_map=True)
                    sub_outputs[sn["id"]] = r
                    continue

                if ntype == "func_define":
                    r = self._execute_define_func(sn, sub_ctx, depth + 1)
                    sub_outputs[sn["id"]] = r
                    continue

                if defn["execute"]:
                    sub_outputs[sn["id"]] = defn["execute"](sub_ctx, sub_inputs)
                else:
                    sub_outputs[sn["id"]] = {}

            except Exception as e:
                raise Exception(f"函数 {closure.name} 内节点 {sn['id']} 执行失败: {e}")

        if return_value is None and closure.return_node_id:
            rn_outputs = sub_outputs.get(closure.return_node_id, {})
            return_value = rn_outputs.get("value")

        return {"return": return_value}

    def _execute_filter_map(self, node, inputs, ctx, depth, call_stack, is_map):
        iterable = inputs.get("iterable")
        func = inputs.get("func")
        arr = list(iterable) if iterable is not None else []

        if not isinstance(func, PyClosure):
            return {"result": arr}

        result = []
        for i, item in enumerate(arr):
            if i >= self.max_iterations:
                raise Exception("达到最大迭代次数")
            call_inputs = {**inputs, "func": func, "arg0": item, "arg1": None}
            r = self._execute_call(node, call_inputs, ctx, depth + 1, call_stack | {node["id"]})
            if is_map:
                result.append(r.get("return"))
            else:
                if r.get("return"):
                    result.append(item)
        return {"result": result}


def run_workflow(nodes, edges, log_callback):
    """运行工作流"""
    interp = Interpreter(nodes, edges, log_callback)
    interp.run()
    return interp

# ============================================================================
# 代码生成器
# ============================================================================

class CodeGenState:
    def __init__(self):
        self.used_names = {"print", "range", "len", "filter", "map", "list",
                           "dict", "set", "tuple", "str", "int", "float", "bool"}
        self.counter = 0

    def gen_var(self, prefix="v"):
        self.counter += 1
        name = f"_{prefix}_{self.counter}"
        while name in self.used_names:
            self.counter += 1
            name = f"_{prefix}_{self.counter}"
        self.used_names.add(name)
        return name


def generate_python(nodes, edges, header=True):
    sorted_nodes = topological_sort(nodes, edges)
    state = CodeGenState()
    port_expr = {}       # "nodeId.portId" -> python expr string
    statements = []
    func_defs = []

    def get_input_expr(node_id, port_id):
        for e in edges:
            if e["to"] == node_id and e["toPort"] == port_id:
                return port_expr.get(f"{e['from']}.{e['fromPort']}", "None")
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            defn = get_node_def(node["type"])
            if defn:
                port = next((p for p in defn["inputs"] if p["id"] == port_id), None)
                if port_id in node.get("params", {}):
                    return py_repr(node["params"][port_id])
                if port and port.get("default") is not None:
                    return py_repr(port["default"])
        return "None"

    for node in sorted_nodes:
        defn = get_node_def(node["type"])
        if not defn:
            continue

        ntype = node["type"]

        # 字面量
        if ntype in ("literal_int", "literal_float", "literal_str", "literal_bool"):
            val = node.get("params", {}).get("value")
            port_expr[f"{node['id']}.value"] = py_repr(val)
            continue

        if ntype == "literal_none":
            port_expr[f"{node['id']}.value"] = "None"
            continue

        # 函数定义
        if ntype == "func_define":
            func_name = state.gen_var("func")
            param_names = [p["id"] for p in defn["inputs"]]
            header_line = f"def {func_name}({', '.join(param_names)}):"

            sub = node.get("subgraph") or {"nodes": [], "edges": []}
            sub_statements = _gen_subgraph_code(sub["nodes"], sub["edges"], param_names, state)
            if not sub_statements:
                sub_statements = ["    pass"]

            func_defs.append(header_line + "\n" + "\n".join(sub_statements))
            port_expr[f"{node['id']}.func"] = func_name
            continue

        # 收集输入表达式
        input_exprs = {}
        for port in defn["inputs"]:
            input_exprs[port["id"]] = get_input_expr(node["id"], port["id"])

        if not defn.get("to_code"):
            continue

        result = defn["to_code"](None, input_exprs)

        if result.get("statements"):
            for stmt in result["statements"]:
                statements.append(stmt)

        for port_id, expr in result.get("assignments", {}).items():
            if expr:
                var_name = state.gen_var()
                statements.append(f"{var_name} = {expr}")
                port_expr[f"{node['id']}.{port_id}"] = var_name
            else:
                port_expr[f"{node['id']}.{port_id}"] = "None"

    lines = []
    if header:
        lines.append("#!/usr/bin/env python3")
        lines.append("# -*- coding: utf-8 -*-")
        lines.append('"""')
        lines.append("由 PyFlowCode 节点式编辑器生成")
        lines.append('"""')
        lines.append("")

    if func_defs:
        lines.extend(func_defs)
        lines.append("")

    if not statements:
        lines.append("pass")
    else:
        lines.extend(statements)

    return "\n".join(lines)


def _gen_subgraph_code(sub_nodes, sub_edges, param_names, state):
    sorted_nodes = topological_sort(sub_nodes, sub_edges)
    port_expr = {}
    statements = []
    indent = "    "

    def get_input_expr(node_id, port_id):
        for e in sub_edges:
            if e["to"] == node_id and e["toPort"] == port_id:
                return port_expr.get(f"{e['from']}.{e['fromPort']}", "None")
        node = next((n for n in sub_nodes if n["id"] == node_id), None)
        if node:
            defn = get_node_def(node["type"])
            if defn:
                port = next((p for p in defn["inputs"] if p["id"] == port_id), None)
                if port_id in param_names:
                    return port_id
                if port_id in node.get("params", {}):
                    return py_repr(node["params"][port_id])
                if port and port.get("default") is not None:
                    return py_repr(port["default"])
        return "None"

    for node in sorted_nodes:
        defn = get_node_def(node["type"])
        if not defn:
            continue

        ntype = node["type"]

        if ntype in ("literal_int", "literal_float", "literal_str", "literal_bool"):
            val = node.get("params", {}).get("value")
            port_expr[f"{node['id']}.value"] = py_repr(val)
            continue

        if ntype == "func_return":
            value_expr = "None"
            for e in sub_edges:
                if e["to"] == node["id"] and e["toPort"] == "value":
                    value_expr = port_expr.get(f"{e['from']}.{e['fromPort']}", "None")
                    break
            statements.append(f"{indent}return {value_expr}")
            continue

        input_exprs = {}
        for port in defn["inputs"]:
            input_exprs[port["id"]] = get_input_expr(node["id"], port["id"])

        if not defn.get("to_code"):
            continue

        result = defn["to_code"](None, input_exprs)

        if result.get("statements"):
            for stmt in result["statements"]:
                statements.append(f"{indent}{stmt}")

        for port_id, expr in result.get("assignments", {}).items():
            if expr:
                var_name = state.gen_var()
                statements.append(f"{indent}{var_name} = {expr}")
                port_expr[f"{node['id']}.{port_id}"] = var_name
            else:
                port_expr[f"{node['id']}.{port_id}"] = "None"

    return statements

# ============================================================================
# 示例工作流
# ============================================================================

EXAMPLES = {
    "hello_world": {
        "name": "Hello World",
        "description": "最简单的字符串打印",
        "format_version": 1,
        "nodes": [
            {"id": "n1", "type": "literal_str", "pos": {"x": 80, "y": 200}, "params": {"value": "Hello, PyFlowCode!"}},
            {"id": "n2", "type": "io_print", "pos": {"x": 380, "y": 200}, "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "fromPort": "value", "to": "n2", "toPort": "value"},
        ],
    },
    "arithmetic": {
        "name": "算术运算",
        "description": "5 + 3 * 2 的运算",
        "format_version": 1,
        "nodes": [
            {"id": "n1", "type": "literal_int", "pos": {"x": 50, "y": 100}, "params": {"value": 5}},
            {"id": "n2", "type": "literal_int", "pos": {"x": 50, "y": 220}, "params": {"value": 3}},
            {"id": "n3", "type": "literal_int", "pos": {"x": 50, "y": 340}, "params": {"value": 2}},
            {"id": "n4", "type": "op_mul", "pos": {"x": 280, "y": 260}, "params": {}},
            {"id": "n5", "type": "op_add", "pos": {"x": 500, "y": 180}, "params": {}},
            {"id": "n6", "type": "io_print", "pos": {"x": 720, "y": 200}, "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n2", "fromPort": "value", "to": "n4", "toPort": "a"},
            {"id": "e2", "from": "n3", "fromPort": "value", "to": "n4", "toPort": "b"},
            {"id": "e3", "from": "n1", "fromPort": "value", "to": "n5", "toPort": "a"},
            {"id": "e4", "from": "n4", "fromPort": "result", "to": "n5", "toPort": "b"},
            {"id": "e5", "from": "n5", "fromPort": "result", "to": "n6", "toPort": "value"},
        ],
    },
    "condition": {
        "name": "条件选择",
        "description": "根据年龄判断是否成年",
        "format_version": 1,
        "nodes": [
            {"id": "n1", "type": "literal_int", "pos": {"x": 50, "y": 100}, "params": {"value": 20}},
            {"id": "n2", "type": "literal_int", "pos": {"x": 50, "y": 220}, "params": {"value": 18}},
            {"id": "n3", "type": "cmp_ge", "pos": {"x": 280, "y": 160}, "params": {}},
            {"id": "n4", "type": "literal_str", "pos": {"x": 280, "y": 320}, "params": {"value": "成年"}},
            {"id": "n5", "type": "literal_str", "pos": {"x": 280, "y": 420}, "params": {"value": "未成年"}},
            {"id": "n6", "type": "control_if", "pos": {"x": 540, "y": 280}, "params": {}},
            {"id": "n7", "type": "io_print", "pos": {"x": 800, "y": 280}, "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "fromPort": "value", "to": "n3", "toPort": "a"},
            {"id": "e2", "from": "n2", "fromPort": "value", "to": "n3", "toPort": "b"},
            {"id": "e3", "from": "n3", "fromPort": "result", "to": "n6", "toPort": "condition"},
            {"id": "e4", "from": "n4", "fromPort": "value", "to": "n6", "toPort": "true_value"},
            {"id": "e5", "from": "n5", "fromPort": "value", "to": "n6", "toPort": "false_value"},
            {"id": "e6", "from": "n6", "fromPort": "selected", "to": "n7", "toPort": "value"},
        ],
    },
    "list_iterate": {
        "name": "列表遍历",
        "description": "构造 range 并打印元素",
        "format_version": 1,
        "nodes": [
            {"id": "n1", "type": "range_node", "pos": {"x": 80, "y": 200}, "params": {"start": 1, "stop": 6, "step": 1}},
            {"id": "n2", "type": "control_for_each", "pos": {"x": 360, "y": 200}, "params": {}},
            {"id": "n3", "type": "io_print", "pos": {"x": 640, "y": 200}, "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "fromPort": "range", "to": "n2", "toPort": "iterable"},
            {"id": "e2", "from": "n2", "fromPort": "items", "to": "n3", "toPort": "value"},
        ],
    },
    "string_format": {
        "name": "字符串格式化",
        "description": "用 f-string 拼接问候语",
        "format_version": 1,
        "nodes": [
            {"id": "n1", "type": "literal_str", "pos": {"x": 50, "y": 100}, "params": {"value": "Alice"}},
            {"id": "n2", "type": "literal_int", "pos": {"x": 50, "y": 240}, "params": {"value": 25}},
            {"id": "n3", "type": "str_format", "pos": {"x": 320, "y": 160}, "params": {"template": "Hello, {0}! You are {1} years old."}},
            {"id": "n4", "type": "io_print", "pos": {"x": 640, "y": 180}, "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "fromPort": "value", "to": "n3", "toPort": "arg0"},
            {"id": "e2", "from": "n2", "fromPort": "value", "to": "n3", "toPort": "arg1"},
            {"id": "e3", "from": "n3", "fromPort": "result", "to": "n4", "toPort": "value"},
        ],
    },
}

# ============================================================================
# ID 生成
# ============================================================================

_id_counter = [0]

def gen_id(prefix="n"):
    _id_counter[0] += 1
    return f"{prefix}_{int(time.time() * 1000)}_{_id_counter[0]}"

# ============================================================================
# Qt UI: 常量
# ============================================================================

NODE_WIDTH = 180
HEADER_HEIGHT = 26
PORT_ROW_HEIGHT = 20
PORT_RADIUS = 5
NODE_BG = QColor("#27272a")
NODE_HEADER_BG = QColor("#3f3f46")
NODE_BORDER = QColor("#52525b")
NODE_SELECTED = QColor("#fbbf24")
TEXT_COLOR = QColor("#e4e4e7")
PORT_LABEL_COLOR = QColor("#a1a1aa")
TYPE_LABEL_COLOR = QColor("#71717a")

# ============================================================================
# Qt UI: EdgeItem
# ============================================================================

class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge_data, from_pos, to_pos, port_type, is_pending=False):
        super().__init__()
        self.edge = edge_data
        self.from_pos = from_pos
        self.to_pos = to_pos
        self.port_type = port_type
        self.is_pending = is_pending
        self.setZValue(0)
        self._update_path()

    def set_endpoints(self, from_pos, to_pos):
        self.from_pos = from_pos
        self.to_pos = to_pos
        self._update_path()

    def _update_path(self):
        path = QPainterPath()
        path.moveTo(self.from_pos)
        dx = abs(self.to_pos.x() - self.from_pos.x())
        cp1 = QPointF(self.from_pos.x() + dx * 0.5, self.from_pos.y())
        cp2 = QPointF(self.to_pos.x() - dx * 0.5, self.to_pos.y())
        path.cubicTo(cp1, cp2, self.to_pos)
        self.setPath(path)

        color = QColor(get_type_color(self.port_type))
        pen = QPen(color, 2)
        if self.is_pending:
            pen.setStyle(Qt.DashLine)
            pen.setWidth(2)
        self.setPen(pen)

    def paint(self, painter, option, widget):
        # 选中时加粗
        if self.isSelected():
            pen = QPen(QColor(get_type_color(self.port_type)), 3)
            self.setPen(pen)
        else:
            color = QColor(get_type_color(self.port_type))
            pen = QPen(color, 2)
            if self.is_pending:
                pen.setStyle(Qt.DashLine)
            self.setPen(pen)
        super().paint(painter, option, widget)

    def shape(self):
        # 加宽点击区域
        path = self.path()
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(path)

# ============================================================================
# Qt UI: NodeItem
# ============================================================================

class NodeItem(QGraphicsItem):
    def __init__(self, node_data, canvas_scene):
        super().__init__()
        self.node = node_data
        self.scene_ref = canvas_scene
        self.def_ = get_node_def(node_data["type"])
        self.width = (self.def_ or {}).get("defaultSize", {}).get("width", NODE_WIDTH) if self.def_ else NODE_WIDTH

        self._dragging = False
        self._drag_start = QPointF(0, 0)
        self._connecting = False
        self._conn_port_id = None

        self.setPos(node_data.get("pos", {}).get("x", 0), node_data.get("pos", {}).get("y", 0))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(2)

        self._calc_layout()

    def _calc_layout(self):
        defn = self.def_
        if not defn:
            self.height = 60
            self.input_ports = {}
            self.output_ports = {}
            return

        n_in = len(defn["inputs"])
        n_out = len(defn["outputs"])
        max_ports = max(n_in, n_out, 1)

        has_param = n_in == 0 and n_out > 0
        param_h = 36 if has_param else 0
        subgraph_h = 18 if defn.get("isSubgraph") else 0
        error_h = 20 if self.node.get("_runtime", {}).get("error") else 0

        self.height = HEADER_HEIGHT + max_ports * PORT_ROW_HEIGHT + param_h + subgraph_h + error_h + 6

        self.input_ports = {}
        for i, port in enumerate(defn["inputs"]):
            y = HEADER_HEIGHT + i * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT // 2
            self.input_ports[port["id"]] = {"pos": QPointF(0, y), "def": port}

        self.output_ports = {}
        for i, port in enumerate(defn["outputs"]):
            y = HEADER_HEIGHT + i * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT // 2
            self.output_ports[port["id"]] = {"pos": QPointF(self.width, y), "def": port}

    def boundingRect(self):
        return QRectF(-2, -2, self.width + 4, self.height + 4)

    def paint(self, painter, option, widget):
        defn = self.def_
        if not defn:
            painter.setPen(QPen(QColor("#ef4444"), 1))
            painter.setBrush(QBrush(QColor("#450a0a")))
            painter.drawRoundedRect(QRectF(0, 0, self.width, self.height), 4, 4)
            painter.setPen(QPen(QColor("#fca5a5")))
            painter.drawText(QRectF(4, 4, self.width - 8, self.height - 8), Qt.AlignCenter, f"未知: {self.node['type']}")
            return

        rect = QRectF(0, 0, self.width, self.height)

        # 选中边框
        is_selected = self.isSelected()
        border_color = NODE_SELECTED if is_selected else NODE_BORDER
        pen_w = 2 if is_selected else 1

        # 状态指示 (左边框)
        status = self.node.get("_runtime", {}).get("status", "idle")
        status_color = {
            "ok": QColor("#10b981"),
            "error": QColor("#ef4444"),
            "running": QColor("#3b82f6"),
        }.get(status)

        # 背景
        painter.setPen(QPen(border_color, pen_w))
        painter.setBrush(QBrush(NODE_BG))
        painter.drawRoundedRect(rect, 4, 4)

        # 左边状态条
        if status_color:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(status_color))
            left_rect = QRectF(0, 4, 4, self.height - 8)
            painter.drawRoundedRect(left_rect, 2, 2)

        # 头部
        header_rect = QRectF(0, 0, self.width, HEADER_HEIGHT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(NODE_HEADER_BG))
        path = QPainterPath()
        path.addRoundedRect(header_rect, 4, 4)
        # 覆盖底部圆角
        path.addRect(QRectF(0, HEADER_HEIGHT - 6, self.width, 6))
        painter.fillPath(path, QBrush(NODE_HEADER_BG))

        # 标题
        title = self.node.get("title") or defn["label"]
        painter.setPen(QPen(TEXT_COLOR))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(header_rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, title)

        # 子图标记
        if defn.get("isSubgraph"):
            painter.setPen(QPen(QColor("#fbbf24")))
            font2 = QFont()
            font2.setPointSize(7)
            painter.setFont(font2)
            painter.drawText(header_rect.adjusted(0, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, "子图")

        # 端口
        for pid, info in self.input_ports.items():
            self._draw_port(painter, info, "input")
        for pid, info in self.output_ports.items():
            self._draw_port(painter, info, "output")

        # 字面量值显示
        if not defn["inputs"] and defn["outputs"]:
            val_rect = QRectF(6, HEADER_HEIGHT + max(len(defn["inputs"]), len(defn["outputs"])) * PORT_ROW_HEIGHT, self.width - 12, 30)
            painter.setPen(QPen(QColor("#3f3f46"), 1))
            painter.setBrush(QBrush(QColor("#18181b")))
            painter.drawRoundedRect(val_rect, 3, 3)

            val = self.node.get("params", {}).get("value")
            val_str = py_repr(val) if val is not None else "None"
            if len(val_str) > 30:
                val_str = val_str[:27] + "..."

            painter.setPen(QPen(QColor("#d4d4d8")))
            font3 = QFont("Courier", 9)
            painter.setFont(font3)
            painter.drawText(val_rect.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, val_str)

        # 子图提示
        if defn.get("isSubgraph"):
            hint_y = self.height - 18
            painter.setPen(QPen(QColor("#fbbf24")))
            font4 = QFont()
            font4.setPointSize(7)
            painter.setFont(font4)
            painter.drawText(QRectF(6, hint_y, self.width - 12, 14), Qt.AlignVCenter | Qt.AlignLeft, "双击进入子图 →")

        # 错误提示
        err = self.node.get("_runtime", {}).get("error")
        if err:
            err_y = self.height - 20
            painter.setPen(QPen(QColor("#7f1d1d"), 1))
            painter.setBrush(QBrush(QColor("#450a0a")))
            painter.drawRect(QRectF(0, err_y, self.width, 20))
            painter.setPen(QPen(QColor("#fca5a5")))
            font5 = QFont()
            font5.setPointSize(7)
            painter.setFont(font5)
            short_err = err[:40] + "..." if len(err) > 40 else err
            painter.drawText(QRectF(6, err_y, self.width - 12, 20), Qt.AlignVCenter | Qt.AlignLeft, f"⚠ {short_err}")

    def _draw_port(self, painter, port_info, direction):
        pos = port_info["pos"]
        port = port_info["def"]
        color = QColor(get_type_color(port["type"]))

        # 端口圆
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(pos, PORT_RADIUS, PORT_RADIUS)

        # 标签
        painter.setPen(QPen(PORT_LABEL_COLOR))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        fm = QFontMetrics(font)

        if direction == "input":
            painter.drawText(QPointF(pos.x() + 10, pos.y() + 4), port["label"])
        else:
            w = fm.horizontalAdvance(port["label"])
            painter.drawText(QPointF(pos.x() - 10 - w, pos.y() + 4), port["label"])

    def _port_at(self, local_pos):
        """检查本地坐标是否在某个端口上, 返回 {'id':..., 'direction':...} 或 None"""
        for pid, info in {**self.input_ports, **self.output_ports}.items():
            p = info["pos"]
            dx = local_pos.x() - p.x()
            dy = local_pos.y() - p.y()
            if dx * dx + dy * dy <= (PORT_RADIUS + 4) ** 2:
                direction = "input" if pid in self.input_ports else "output"
                return {"id": pid, "direction": direction, "def": info["def"]}
        return None

    def get_port_scene_pos(self, port_id, direction):
        if direction == "input" and port_id in self.input_ports:
            return self.mapToScene(self.input_ports[port_id]["pos"])
        if direction == "output" and port_id in self.output_ports:
            return self.mapToScene(self.output_ports[port_id]["pos"])
        return None

    def get_port_type(self, port_id, direction):
        if direction == "input" and port_id in self.input_ports:
            return self.input_ports[port_id]["def"]["type"]
        if direction == "output" and port_id in self.output_ports:
            return self.output_ports[port_id]["def"]["type"]
        return "any"

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        local = event.pos()
        port = self._port_at(local)

        # 端口点击 - 开始连线
        if port and port["direction"] == "output":
            self._connecting = True
            self._conn_port_id = port["id"]
            self.scene_ref.start_connection(self.node["id"], port["id"], event.scenePos())
            self.grabMouse()
            event.accept()
            return

        # 头部点击 - 开始拖拽
        if local.y() < HEADER_HEIGHT:
            self._dragging = True
            self._drag_start = event.scenePos() - self.pos()
            self.setSelected(True)
            event.accept()
            return

        # 其他区域 - 选中节点
        self.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._connecting:
            self.scene_ref.update_connection(event.scenePos())
            event.accept()
            return
        if self._dragging:
            self.setPos(event.scenePos() - self._drag_start)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._connecting:
            # 检查鼠标下是否有输入端口
            items = self.scene().items(event.scenePos())
            for item in items:
                if isinstance(item, NodeItem) and item != self:
                    local = item.mapFromScene(event.scenePos())
                    port = item._port_at(local)
                    if port and port["direction"] == "input":
                        self.scene_ref.finish_connection(
                            self.node["id"], self._conn_port_id,
                            item.node["id"], port["id"]
                        )
                        break
            self.scene_ref.cancel_connection()
            self._connecting = False
            self._conn_port_id = None
            self.ungrabMouse()
            event.accept()
            return
        if self._dragging:
            self._dragging = False
            # 更新节点数据中的位置
            self.node["pos"] = {"x": self.pos().x(), "y": self.pos().y()}
            self.scene_ref.on_node_moved(self.node["id"])
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        defn = self.def_
        if defn and defn.get("isSubgraph"):
            self.scene_ref.enter_subgraph(self.node["id"])
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.scene_ref.on_selection_changed()
        return super().itemChange(change, value)

# ============================================================================
# Qt UI: CanvasScene
# ============================================================================

class CanvasScene(QGraphicsScene):
    node_selected = Signal(object)
    selection_changed = Signal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.node_items = {}       # node_id -> NodeItem
        self.edge_items = {}       # edge_id -> EdgeItem
        self.pending_edge = None
        self.pending_from_node = None
        self.pending_from_port = None

    def load_graph(self, nodes, edges):
        self.clear()
        self.node_items = {}
        self.edge_items = {}
        self.pending_edge = None

        for node in nodes:
            self.add_node_item(node)

        for edge in edges:
            self.add_edge_item(edge)

    def add_node_item(self, node_data):
        item = NodeItem(node_data, self)
        self.addItem(item)
        self.node_items[node_data["id"]] = item
        return item

    def remove_node_item(self, node_id):
        item = self.node_items.pop(node_id, None)
        if item:
            self.removeItem(item)

    def add_edge_item(self, edge_data):
        from_item = self.node_items.get(edge_data["from"])
        to_item = self.node_items.get(edge_data["to"])
        if not from_item or not to_item:
            return
        from_pos = from_item.get_port_scene_pos(edge_data["fromPort"], "output")
        to_pos = to_item.get_port_scene_pos(edge_data["toPort"], "input")
        if not from_pos or not to_pos:
            return
        port_type = from_item.get_port_type(edge_data["fromPort"], "output")
        edge_item = EdgeItem(edge_data, from_pos, to_pos, port_type)
        edge_item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.addItem(edge_item)
        self.edge_items[edge_data["id"]] = edge_item

    def remove_edge_item(self, edge_id):
        item = self.edge_items.pop(edge_id, None)
        if item:
            self.removeItem(item)

    def update_node_edges(self, node_id):
        """当节点移动时, 更新所有相关连线"""
        for edge_id, edge_item in list(self.edge_items.items()):
            e = edge_item.edge
            if e["from"] == node_id or e["to"] == node_id:
                from_item = self.node_items.get(e["from"])
                to_item = self.node_items.get(e["to"])
                if from_item and to_item:
                    from_pos = from_item.get_port_scene_pos(e["fromPort"], "output")
                    to_pos = to_item.get_port_scene_pos(e["toPort"], "input")
                    if from_pos and to_pos:
                        edge_item.set_endpoints(from_pos, to_pos)

    def start_connection(self, from_node_id, from_port_id, scene_pos):
        self.pending_from_node = from_node_id
        self.pending_from_port = from_port_id
        from_item = self.node_items.get(from_node_id)
        if from_item:
            port_type = from_item.get_port_type(from_port_id, "output")
            from_pos = from_item.get_port_scene_pos(from_port_id, "output")
            if from_pos:
                self.pending_edge = EdgeItem(
                    {"id": "pending"},
                    from_pos, scene_pos,
                    port_type, is_pending=True
                )
                self.addItem(self.pending_edge)

    def update_connection(self, scene_pos):
        if self.pending_edge:
            from_item = self.node_items.get(self.pending_from_node)
            if from_item:
                from_pos = from_item.get_port_scene_pos(self.pending_from_port, "output")
                if from_pos:
                    self.pending_edge.set_endpoints(from_pos, scene_pos)

    def finish_connection(self, from_node, from_port, to_node, to_port):
        # 类型检查
        from_item = self.node_items.get(from_node)
        to_item = self.node_items.get(to_node)
        if not from_item or not to_item:
            return
        from_type = from_item.get_port_type(from_port, "output")
        to_type = to_item.get_port_type(to_port, "input")
        if not is_type_compatible(from_type, to_type):
            return

        # 检查目标端口是否已有连线 (非 multi)
        to_def = to_item.def_
        if to_def:
            to_port_def = next((p for p in to_def["inputs"] if p["id"] == to_port), None)
            if to_port_def and not to_port_def.get("multi"):
                # 删除已有连线
                self.main_window.remove_edge_to_port(to_node, to_port)

        # 添加连线
        edge_id = gen_id("e")
        edge_data = {
            "id": edge_id,
            "from": from_node,
            "fromPort": from_port,
            "to": to_node,
            "toPort": to_port,
        }
        self.main_window.add_edge_to_current(edge_data)
        self.add_edge_item(edge_data)

    def cancel_connection(self):
        if self.pending_edge:
            self.removeItem(self.pending_edge)
            self.pending_edge = None
        self.pending_from_node = None
        self.pending_from_port = None

    def on_node_moved(self, node_id):
        self.update_node_edges(node_id)

    def on_selection_changed(self):
        items = self.selectedItems()
        for item in items:
            if isinstance(item, NodeItem):
                self.main_window.on_node_selected(item.node["id"])
                return
            elif isinstance(item, EdgeItem):
                self.main_window.on_edge_selected(item.edge["id"])
                return
        self.main_window.on_node_selected(None)

    def enter_subgraph(self, node_id):
        self.main_window.enter_subgraph(node_id)

# ============================================================================
# Qt UI: CanvasView (平移/缩放/网格背景)
# ============================================================================

class CanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor("#1a1a1f")))

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)
        # 限制缩放范围
        zoom = self.transform().m11()
        if zoom < 0.2:
            self.resetTransform()
            self.scale(0.2, 0.2)
        elif zoom > 3.0:
            self.resetTransform()
            self.scale(3.0, 3.0)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#1a1a1f"))

        # 网格
        grid_size = 24
        painter.setPen(QPen(QColor("#2a2a32"), 1))
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)
        for x in range(left, int(rect.right()) + 1, grid_size):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()) + 1, grid_size):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def mousePressEvent(self, event):
        # 中键或空格+左键 平移
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            # 模拟左键按下
            fake = event.clone()
            fake.setButton(Qt.LeftButton)
            super().mousePressEvent(fake)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.RubberBandDrag)
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        node_type = event.mimeData().text()
        if node_type and get_node_def(node_type):
            pos = self.mapToScene(event.position().toPoint())
            self.scene().main_window.add_node(node_type, pos)

# ============================================================================
# Qt UI: NodePalette (左侧节点面板)
# ============================================================================

class NodePalette(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setFixedWidth(220)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 搜索框
        search_frame = QFrame()
        search_frame.setStyleSheet("QFrame { background: #1e1e24; border-bottom: 1px solid #3f3f46; }")
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(8, 8, 8, 8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索节点...")
        self.search_box.setStyleSheet("""
            QLineEdit {
                background: #18181b; color: #e4e4e7;
                border: 1px solid #3f3f46; border-radius: 3px;
                padding: 4px 8px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #fbbf24; }
        """)
        self.search_box.textChanged.connect(self._filter)
        search_layout.addWidget(self.search_box)
        layout.addWidget(search_frame)

        # 节点树
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background: #1e1e24; color: #e4e4e7;
                border: none; font-size: 12px;
            }
            QTreeWidget::item { padding: 3px 4px; }
            QTreeWidget::item:hover { background: #3f3f46; }
            QTreeWidget::item:selected { background: #fbbf24; color: #18181b; }
        """)

        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QTreeWidget.DragOnly)

        self._populate()
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree)

        # 启动拖拽
        self.tree.startDrag = self._start_drag

    def _populate(self):
        self.tree.clear()
        by_cat = list_nodes_by_category()
        for cat, nodes in by_cat.items():
            if not nodes:
                continue
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, f"{CATEGORY_ICONS.get(cat, '')}  {CATEGORY_LABELS.get(cat, cat)}")
            cat_item.setFont(0, QFont("", 9, QFont.Bold))
            cat_item.setForeground(0, QColor("#a1a1aa"))
            cat_item.setExpanded(True)

            for defn in nodes:
                child = QTreeWidgetItem(cat_item)
                child.setText(0, defn["label"])
                child.setData(0, Qt.UserRole, defn["type"])
                child.setToolTip(0, defn.get("description", ""))

    def _filter(self, text):
        text = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            visible_count = 0
            for j in range(cat.childCount()):
                child = cat.child(j)
                label = child.text(0).lower()
                type_id = child.data(0, Qt.UserRole) or ""
                if not text or text in label or text in type_id:
                    child.setHidden(False)
                    visible_count += 1
                else:
                    child.setHidden(True)
            cat.setHidden(visible_count == 0)
            cat.setExpanded(True if text else True)

    def _on_double_click(self, item):
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            self.main_window.add_node(type_id, None)

    def _start_drag(self, *args):
        item = self.tree.currentItem()
        if item:
            type_id = item.data(0, Qt.UserRole)
            if type_id:
                from PySide6.QtCore import QMimeData
                mime = QMimeData()
                mime.setText(type_id)
                from PySide6.QtGui import QDrag
                drag = QDrag(self)
                drag.setMimeData(mime)
                drag.exec_()

# ============================================================================
# Qt UI: PropertiesPanel (右侧属性面板)
# ============================================================================

class PropertiesPanel(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.current_node_id = None
        self._build_ui()

    def _build_ui(self):
        self.setFixedWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        title = QLabel("属性")
        title.setStyleSheet("""
            QLabel {
                background: #1e1e24; color: #a1a1aa;
                padding: 8px 12px; font-size: 11px;
                font-weight: bold; border-bottom: 1px solid #3f3f46;
                text-transform: uppercase; letter-spacing: 1px;
            }
        """)
        layout.addWidget(title)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e24; }")

        self.content = QWidget()
        self.content.setStyleSheet("QWidget { background: #1e1e24; }")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(8)

        scroll.setWidget(self.content)
        layout.addWidget(scroll)

        self._show_empty()

    def _show_empty(self):
        self._clear_content()
        lbl = QLabel("未选中节点\n\n点击画布中的节点查看属性")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #71717a; font-size: 12px;")
        self.content_layout.addWidget(lbl)
        self.content_layout.addStretch()

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_node(self, node_id):
        self.current_node_id = node_id
        self._clear_content()

        if not node_id:
            self._show_empty()
            return

        nodes = self.main_window.get_current_nodes()
        node = next((n for n in nodes if n["id"] == node_id), None)
        if not node:
            self._show_empty()
            return

        defn = get_node_def(node["type"])
        if not defn:
            lbl = QLabel(f"未知节点类型: {node['type']}")
            lbl.setStyleSheet("color: #ef4444;")
            self.content_layout.addWidget(lbl)
            return

        # 节点信息
        info = QLabel(f"节点类型")
        info.setStyleSheet("color: #71717a; font-size: 10px; text-transform: uppercase; letter-spacing: 1px;")
        self.content_layout.addWidget(info)

        name_lbl = QLabel(defn["label"])
        name_lbl.setStyleSheet("color: #e4e4e7; font-size: 14px; font-weight: bold;")
        self.content_layout.addWidget(name_lbl)

        id_lbl = QLabel(node["id"])
        id_lbl.setStyleSheet("color: #52525b; font-size: 10px; font-family: monospace;")
        self.content_layout.addWidget(id_lbl)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #3f3f46;")
        self.content_layout.addWidget(sep)

        # 显示名称
        title_label = QLabel("显示名称")
        title_label.setStyleSheet("color: #71717a; font-size: 10px; text-transform: uppercase; letter-spacing: 1px;")
        self.content_layout.addWidget(title_label)

        title_edit = QLineEdit(node.get("title") or "")
        title_edit.setPlaceholderText(defn["label"])
        title_edit.setStyleSheet(self._input_style())
        title_edit.textChanged.connect(lambda t: self.main_window.update_node_title(node_id, t))
        self.content_layout.addWidget(title_edit)

        # 描述
        if defn.get("description"):
            desc_label = QLabel("描述")
            desc_label.setStyleSheet("color: #71717a; font-size: 10px; text-transform: uppercase; letter-spacing: 1px;")
            self.content_layout.addWidget(desc_label)
            desc = QLabel(defn["description"])
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #a1a1aa; font-size: 11px;")
            self.content_layout.addWidget(desc)

        # 输入端口
        edges = self.main_window.get_current_edges()
        if defn["inputs"]:
            self.content_layout.addWidget(self._section_label("输入端口"))
            for port in defn["inputs"]:
                has_conn = any(e["to"] == node_id and e["toPort"] == port["id"] for e in edges)
                port_widget = self._make_port_editor(node_id, port, has_conn)
                self.content_layout.addWidget(port_widget)

        # 输出值 (运行后)
        if defn["outputs"] and node.get("_runtime", {}).get("outputs"):
            self.content_layout.addWidget(self._section_label("运行时输出"))
            for port in defn["outputs"]:
                val = node["_runtime"]["outputs"].get(port["id"])
                val_str = py_repr(val) if val is not None else "None"
                if len(val_str) > 60:
                    val_str = val_str[:57] + "..."

                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)

                dot = QLabel("●")
                dot.setStyleSheet(f"color: {get_type_color(port['type'])}; font-size: 10px;")
                row_layout.addWidget(dot)

                lbl = QLabel(port["label"])
                lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
                lbl.setFixedWidth(60)
                row_layout.addWidget(lbl)

                val_lbl = QLabel(val_str)
                val_lbl.setStyleSheet("color: #d4d4d8; font-size: 11px; font-family: monospace;")
                val_lbl.setWordWrap(True)
                row_layout.addWidget(val_lbl, 1)

                self.content_layout.addWidget(row)

        # 子图入口
        if defn.get("isSubgraph"):
            btn = QPushButton("进入子图编辑 →")
            btn.setStyleSheet("""
                QPushButton {
                    background: #78350f; color: #fbbf24;
                    border: 1px solid #92400e; border-radius: 3px;
                    padding: 6px; font-size: 12px;
                }
                QPushButton:hover { background: #92400e; }
            """)
            btn.clicked.connect(lambda: self.main_window.enter_subgraph(node_id))
            self.content_layout.addWidget(btn)

        # 删除按钮
        self.content_layout.addStretch()
        del_btn = QPushButton("🗑  删除节点 (Delete)")
        del_btn.setStyleSheet("""
            QPushButton {
                background: #450a0a; color: #fca5a5;
                border: 1px solid #7f1d1d; border-radius: 3px;
                padding: 6px; font-size: 12px;
            }
            QPushButton:hover { background: #7f1d1d; }
        """)
        del_btn.clicked.connect(lambda: self.main_window.delete_node(node_id))
        self.content_layout.addWidget(del_btn)

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #71717a; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; margin-top: 8px;")
        return lbl

    def _input_style(self):
        return """
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background: #18181b; color: #e4e4e7;
                border: 1px solid #3f3f46; border-radius: 3px;
                padding: 4px 6px; font-size: 12px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border-color: #fbbf24;
            }
        """

    def _make_port_editor(self, node_id, port, has_conn):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 端口标签行
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {get_type_color(port['type'])}; font-size: 10px;")
        row_layout.addWidget(dot)

        lbl = QLabel(port["label"])
        lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        row_layout.addWidget(lbl, 1)

        type_lbl = QLabel(port["type"])
        type_lbl.setStyleSheet(f"color: {get_type_color(port['type'])}; font-size: 9px; font-family: monospace;")
        row_layout.addWidget(type_lbl)

        layout.addWidget(row)

        if has_conn:
            conn_lbl = QLabel("已连接")
            conn_lbl.setStyleSheet("color: #52525b; font-size: 10px; font-style: italic; padding-left: 16px;")
            layout.addWidget(conn_lbl)
        else:
            # 参数编辑器
            editor = self._make_value_editor(node_id, port)
            if editor:
                layout.addWidget(editor)

        return widget

    def _make_value_editor(self, node_id, port):
        nodes = self.main_window.get_current_nodes()
        node = next((n for n in nodes if n["id"] == node_id), None)
        if not node:
            return None

        current_val = node.get("params", {}).get(port["id"], port.get("default"))

        if port["type"] == "int":
            editor = QSpinBox()
            editor.setRange(-999999, 999999)
            editor.setValue(current_val if isinstance(current_val, (int, float)) else 0)
            editor.setStyleSheet(self._input_style())
            editor.valueChanged.connect(lambda v: self.main_window.update_node_param(node_id, port["id"], v))
            return editor

        if port["type"] == "float":
            editor = QDoubleSpinBox()
            editor.setRange(-999999.0, 999999.0)
            editor.setDecimals(6)
            editor.setValue(current_val if isinstance(current_val, (int, float)) else 0.0)
            editor.setStyleSheet(self._input_style())
            editor.valueChanged.connect(lambda v: self.main_window.update_node_param(node_id, port["id"], v))
            return editor

        if port["type"] == "bool":
            editor = QComboBox()
            editor.addItem("False", False)
            editor.addItem("True", True)
            editor.setCurrentIndex(1 if current_val else 0)
            editor.setStyleSheet(self._input_style())
            editor.currentIndexChanged.connect(lambda idx: self.main_window.update_node_param(node_id, port["id"], editor.itemData(idx)))
            return editor

        if port["type"] == "str":
            editor = QLineEdit()
            editor.setText(current_val if isinstance(current_val, str) else "")
            editor.setStyleSheet(self._input_style())
            editor.textChanged.connect(lambda t: self.main_window.update_node_param(node_id, port["id"], t))
            return editor

        return None

# ============================================================================
# Qt UI: ConsolePanel (右侧控制台)
# ============================================================================

class ConsolePanel(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QWidget()
        header.setStyleSheet("background: #1e1e24; border-bottom: 1px solid #3f3f46;")
        header.setFixedHeight(30)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)

        lbl = QLabel("控制台")
        lbl.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: bold;")
        h_layout.addWidget(lbl)

        h_layout.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setStyleSheet("""
            QPushButton {
                background: #27272a; color: #a1a1aa;
                border: 1px solid #3f3f46; border-radius: 2px;
                padding: 2px 8px; font-size: 10px;
            }
            QPushButton:hover { background: #3f3f46; }
        """)
        clear_btn.clicked.connect(self.clear)
        h_layout.addWidget(clear_btn)

        layout.addWidget(header)

        # 输出区
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("""
            QPlainTextEdit {
                background: #1a1a1f; color: #e4e4e7;
                border: none; font-family: 'Courier New', monospace;
                font-size: 11px; padding: 4px;
            }
        """)
        layout.addWidget(self.output)

    def append(self, message, msg_type="log"):
        color = {
            "log": "#e4e4e7",
            "info": "#38bdf8",
            "error": "#f87171",
        }.get(msg_type, "#e4e4e7")
        timestamp = time.strftime("%H:%M:%S")
        self.output.appendHtml(f'<span style="color:#52525b">[{timestamp}]</span> <span style="color:{color}">{message}</span>')

    def clear(self):
        self.output.clear()

# ============================================================================
# Qt UI: CodeGenDialog (代码生成对话框)
# ============================================================================

class CodeGenDialog(QDialog):
    def __init__(self, code, parent=None):
        super().__init__(parent)
        self.code = code
        self.setWindowTitle("生成的 Python 代码")
        self.setMinimumSize(700, 500)
        self.setStyleSheet("background: #1e1e24; color: #e4e4e7;")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 按钮栏
        btn_bar = QWidget()
        btn_bar.setStyleSheet("background: #1e1e24; border-bottom: 1px solid #3f3f46;")
        btn_bar.setFixedHeight(40)
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(12, 0, 12, 0)

        title = QLabel("生成的 Python 代码")
        title.setStyleSheet("color: #38bdf8; font-size: 13px; font-weight: bold;")
        btn_layout.addWidget(title)
        btn_layout.addStretch()

        copy_btn = QPushButton("复制")
        copy_btn.setStyleSheet("""
            QPushButton {
                background: #1e3a5f; color: #38bdf8;
                border: 1px solid #1e40af; border-radius: 3px;
                padding: 4px 12px; font-size: 12px;
            }
            QPushButton:hover { background: #1e40af; }
        """)
        copy_btn.clicked.connect(self._copy)
        btn_layout.addWidget(copy_btn)

        save_btn = QPushButton("下载 .py")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #1e3a5f; color: #38bdf8;
                border: 1px solid #1e40af; border-radius: 3px;
                padding: 4px 12px; font-size: 12px;
            }
            QPushButton:hover { background: #1e40af; }
        """)
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        close_btn = QPushButton("✕")
        close_btn.setStyleSheet("""
            QPushButton {
                background: #27272a; color: #a1a1aa;
                border: 1px solid #3f3f46; border-radius: 3px;
                padding: 4px 8px; font-size: 12px;
            }
            QPushButton:hover { background: #3f3f46; }
        """)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addWidget(btn_bar)

        # 代码区
        self.code_edit = QPlainTextEdit()
        self.code_edit.setReadOnly(True)
        self.code_edit.setPlainText(self.code)
        self.code_edit.setStyleSheet("""
            QPlainTextEdit {
                background: #18181b; color: #d4d4d8;
                border: none; font-family: 'Courier New', monospace;
                font-size: 12px; padding: 12px;
            }
        """)
        layout.addWidget(self.code_edit)

    def _copy(self):
        QApplication.clipboard().setText(self.code)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存 Python 文件", "pyflow_generated.py", "Python Files (*.py)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.code)

# ============================================================================
# Qt UI: MainWindow
# ============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyFlowCode — 节点式 Python 代码可视化编辑器")
        self.setMinimumSize(1200, 750)

        self.document = {"format_version": 1, "nodes": [], "edges": []}
        self.subgraph_path = []  # list of node IDs
        self.selected_node_id = None

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()
        self._apply_dark_theme()
        self._setup_shortcuts()

        # 加载默认示例
        self.load_document(EXAMPLES["hello_world"])
        self.console.append("欢迎使用 PyFlowCode! 已载入 Hello World 示例", "info")
        self.console.append("提示: 从左侧拖入节点, 拖拽端口连线, 点击\"运行\"执行", "info")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧: 节点面板
        self.palette = NodePalette(self)
        layout.addWidget(self.palette)

        # 中间: 画布
        self.scene = CanvasScene(self)
        self.view = CanvasView(self.scene)
        layout.addWidget(self.view, 1)

        # 右侧: 属性 + 控制台 (上下分割)
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setStyleSheet("QSplitter { background: #1e1e24; }")
        right_splitter.setHandleWidth(2)

        self.properties = PropertiesPanel(self)
        right_splitter.addWidget(self.properties)

        self.console = ConsolePanel()
        right_splitter.addWidget(self.console)

        right_splitter.setSizes([400, 250])
        right_splitter.setFixedWidth(280)
        layout.addWidget(right_splitter)

    def _build_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setStyleSheet("""
            QToolBar {
                background: #1e1e24; border: none;
                border-bottom: 1px solid #3f3f46; padding: 4px; spacing: 2px;
            }
            QToolBar QToolButton {
                color: #d4d4d8; padding: 4px 10px;
                border-radius: 3px; font-size: 12px;
            }
            QToolBar QToolButton:hover { background: #3f3f46; }
            QToolBar QToolButton:pressed { background: #52525b; }
        """)

        # Logo
        logo = QLabel("  Py")
        logo.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #fbbf24, stop:1 #ea580c);
                color: white; font-weight: bold; font-size: 12px;
                padding: 4px 8px; border-radius: 3px; margin-right: 8px;
            }
        """)
        toolbar.addWidget(logo)

        title_lbl = QLabel("PyFlowCode  ")
        title_lbl.setStyleSheet("color: #e4e4e7; font-size: 13px; font-weight: bold; margin-right: 12px;")
        toolbar.addWidget(title_lbl)

        # 运行
        run_action = QAction("▶ 运行", self)
        run_action.triggered.connect(self.run_workflow)
        toolbar.addAction(run_action)

        # 生成代码
        code_action = QAction("</> 生成 Python", self)
        code_action.triggered.connect(self.generate_code)
        toolbar.addAction(code_action)

        toolbar.addSeparator()

        # 导出
        export_action = QAction("💾 导出", self)
        export_action.triggered.connect(self.export_document)
        toolbar.addAction(export_action)

        # 导入
        import_action = QAction("📂 导入", self)
        import_action.triggered.connect(self.import_document)
        toolbar.addAction(import_action)

        toolbar.addSeparator()

        # 示例
        examples_btn = QAction("📚 示例", self)
        examples_btn.triggered.connect(self._show_examples_menu)
        toolbar.addAction(examples_btn)

        # 清空
        clear_action = QAction("🗑 清空", self)
        clear_action.triggered.connect(self.clear_canvas)
        toolbar.addAction(clear_action)

        # 子图导航 (面包屑)
        self.breadcrumb_widget = QWidget()
        self.breadcrumb_widget.setVisible(False)
        bc_layout = QHBoxLayout(self.breadcrumb_widget)
        bc_layout.setContentsMargins(8, 0, 0, 0)
        bc_layout.setSpacing(2)

        root_btn = QPushButton("顶层")
        root_btn.setStyleSheet(self._breadcrumb_btn_style())
        root_btn.clicked.connect(lambda: self.navigate_to(-1))
        bc_layout.addWidget(root_btn)

        self.breadcrumb_layout = bc_layout

        back_btn = QPushButton("← 返回")
        back_btn.setStyleSheet(self._breadcrumb_btn_style())
        back_btn.clicked.connect(self.exit_subgraph)
        bc_layout.addWidget(back_btn)

        toolbar.addWidget(self.breadcrumb_widget)

        # 右侧状态
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        self.node_count_label = QLabel("0 节点  0 连线")
        self.node_count_label.setStyleSheet("color: #71717a; font-size: 11px; margin-right: 8px;")
        toolbar.addWidget(self.node_count_label)

        self.addToolBar(toolbar)

    def _breadcrumb_btn_style(self):
        return """
            QPushButton {
                background: #27272a; color: #fbbf24;
                border: 1px solid #3f3f46; border-radius: 3px;
                padding: 2px 8px; font-size: 11px;
            }
            QPushButton:hover { background: #3f3f46; }
        """

    def _build_statusbar(self):
        sb = QStatusBar()
        sb.setStyleSheet("""
            QStatusBar {
                background: #1e1e24; color: #71717a;
                border-top: 1px solid #3f3f46; font-size: 11px;
            }
        """)
        self.status_label = QLabel("就绪")
        sb.addWidget(self.status_label)

        self.zoom_label = QLabel("缩放: 100%")
        sb.addPermanentWidget(self.zoom_label)

        self.setStatusBar(sb)

        # 定时更新缩放显示
        timer = QTimer(self)
        timer.timeout.connect(self._update_zoom_label)
        timer.start(200)

    def _update_zoom_label(self):
        zoom = self.view.transform().m11()
        self.zoom_label.setText(f"缩放: {int(zoom * 100)}%")

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background: #1a1a1f; }
            QWidget { color: #e4e4e7; }
            QToolTip {
                background: #27272a; color: #e4e4e7;
                border: 1px solid #3f3f46; padding: 4px;
            }
            QMenu {
                background: #1e1e24; color: #e4e4e7;
                border: 1px solid #3f3f46;
            }
            QMenu::item { padding: 6px 24px; }
            QMenu::item:selected { background: #3f3f46; }
            QMenu::separator { height: 1px; background: #3f3f46; }
        """)

    def _setup_shortcuts(self):
        # Delete 删除选中
        del_shortcut = QShortcut(QKeySequence.Delete, self)
        del_shortcut.activated.connect(self._delete_selected)
        backspace = QShortcut(QKeySequence.Backspace, self)
        backspace.activated.connect(self._delete_selected)

        # Ctrl+S 保存
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.export_document)

        # Ctrl+O 打开
        open_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        open_shortcut.activated.connect(self.import_document)

        # Ctrl+R 运行
        run_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        run_shortcut.activated.connect(self.run_workflow)

        # F5 运行
        f5 = QShortcut(QKeySequence("F5"), self)
        f5.activated.connect(self.run_workflow)

    # ------------------------------------------------------------------------
    # 工作流数据访问
    # ------------------------------------------------------------------------

    def get_current_container(self):
        """获取当前层级的 (nodes, edges) 引用"""
        nodes = self.document["nodes"]
        edges = self.document["edges"]
        for nid in self.subgraph_path:
            node = next((n for n in nodes if n["id"] == nid), None)
            if node and "subgraph" in node:
                nodes = node["subgraph"]["nodes"]
                edges = node["subgraph"]["edges"]
            else:
                break
        return nodes, edges

    def get_current_nodes(self):
        return self.get_current_container()[0]

    def get_current_edges(self):
        return self.get_current_container()[1]

    def _deep_get_current_container(self):
        """获取当前层级的 (nodes, edges) 容器 (用于修改)"""
        if not self.subgraph_path:
            return self.document["nodes"], self.document["edges"]
        nodes = self.document["nodes"]
        edges = self.document["edges"]
        for nid in self.subgraph_path:
            node = next((n for n in nodes if n["id"] == nid), None)
            if node:
                if "subgraph" not in node:
                    node["subgraph"] = {"nodes": [], "edges": []}
                nodes = node["subgraph"]["nodes"]
                edges = node["subgraph"]["edges"]
        return nodes, edges

    def reload_canvas(self):
        nodes, edges = self.get_current_container()
        self.scene.load_graph(nodes, edges)
        self._update_breadcrumb()
        self._update_counts()
        self.properties.show_node(None)

    def _update_breadcrumb(self):
        if not self.subgraph_path:
            self.breadcrumb_widget.setVisible(False)
            return

        self.breadcrumb_widget.setVisible(True)
        # 清除旧面包屑 (保留第一个"顶层"和最后的"返回")
        while self.breadcrumb_layout.count() > 2:
            item = self.breadcrumb_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        for i, nid in enumerate(self.subgraph_path):
            node = self._find_node_by_id(nid)
            label = node.get("title") or get_node_def(node["type"])["label"] if node and get_node_def(node["type"]) else nid

            sep = QLabel("/")
            sep.setStyleSheet("color: #52525b; font-size: 11px;")
            self.breadcrumb_layout.insertWidget(self.breadcrumb_layout.count() - 1, sep)

            btn = QPushButton(label)
            btn.setStyleSheet(self._breadcrumb_btn_style())
            btn.clicked.connect(lambda checked, idx=i: self.navigate_to(idx))
            self.breadcrumb_layout.insertWidget(self.breadcrumb_layout.count() - 1, btn)

    def _find_node_by_id(self, node_id, nodes=None):
        if nodes is None:
            nodes = self.document["nodes"]
        for n in nodes:
            if n["id"] == node_id:
                return n
            if "subgraph" in n:
                found = self._find_node_by_id(node_id, n["subgraph"]["nodes"])
                if found:
                    return found
        return None

    def _update_counts(self):
        nodes, edges = self.get_current_container()
        self.node_count_label.setText(f"{len(nodes)} 节点  {len(edges)} 连线")

    # ------------------------------------------------------------------------
    # 节点操作
    # ------------------------------------------------------------------------

    def add_node(self, node_type, pos=None):
        defn = get_node_def(node_type)
        if not defn:
            return

        node_id = gen_id("n")
        if pos is None:
            # 添加到画布中央
            center = self.view.mapToScene(self.view.viewport().rect().center())
            pos = QPointF(center.x() - 80, center.y() - 40)

        params = {}
        for port in defn["inputs"]:
            if "default" in port:
                params[port["id"]] = port["default"]
        # 字面量节点的值
        if node_type in ("literal_int", "literal_float", "literal_str", "literal_bool"):
            params["value"] = defn["outputs"][0].get("default")

        node = {
            "id": node_id,
            "type": node_type,
            "pos": {"x": pos.x(), "y": pos.y()},
            "params": params,
        }

        if defn.get("isSubgraph"):
            node["subgraph"] = {"nodes": [], "edges": []}
            node["title"] = "my_func"

        nodes, _ = self._deep_get_current_container()
        nodes.append(node)
        self.scene.add_node_item(node)
        self._update_counts()

    def delete_node(self, node_id):
        nodes, edges = self._deep_get_current_container()
        # 删除节点
        nodes[:] = [n for n in nodes if n["id"] != node_id]
        # 删除相关连线
        removed_edges = [e for e in edges if e["from"] == node_id or e["to"] == node_id]
        edges[:] = [e for e in edges if e["from"] != node_id and e["to"] != node_id]
        # 删除 UI
        self.scene.remove_node_item(node_id)
        for e in removed_edges:
            self.scene.remove_edge_item(e["id"])
        if self.selected_node_id == node_id:
            self.selected_node_id = None
            self.properties.show_node(None)
        self._update_counts()

    def update_node_param(self, node_id, port_id, value):
        nodes, _ = self._deep_get_current_container()
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            node["params"][port_id] = value
            # 刷新节点显示
            item = self.scene.node_items.get(node_id)
            if item:
                item._calc_layout()
                item.update()
                self.scene.update_node_edges(node_id)

    def update_node_title(self, node_id, title):
        nodes, _ = self._deep_get_current_container()
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            node["title"] = title
            item = self.scene.node_items.get(node_id)
            if item:
                item.update()
            self._update_breadcrumb()

    def on_node_selected(self, node_id):
        self.selected_node_id = node_id
        self.properties.show_node(node_id)

    def on_edge_selected(self, edge_id):
        self.properties.show_node(None)

    def _delete_selected(self):
        # 检查是否有焦点在输入框上
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit)):
            return
        for item in self.scene.selectedItems():
            if isinstance(item, NodeItem):
                self.delete_node(item.node["id"])
            elif isinstance(item, EdgeItem):
                self._delete_edge(item.edge["id"])

    def _delete_edge(self, edge_id):
        _, edges = self._deep_get_current_container()
        edges[:] = [e for e in edges if e["id"] != edge_id]
        self.scene.remove_edge_item(edge_id)
        self._update_counts()

    # ------------------------------------------------------------------------
    # 连线操作
    # ------------------------------------------------------------------------

    def add_edge_to_current(self, edge_data):
        _, edges = self._deep_get_current_container()
        edges.append(edge_data)
        self._update_counts()

    def remove_edge_to_port(self, to_node, to_port):
        _, edges = self._deep_get_current_container()
        removed = [e for e in edges if e["to"] == to_node and e["toPort"] == to_port]
        edges[:] = [e for e in edges if not (e["to"] == to_node and e["toPort"] == to_port)]
        for e in removed:
            self.scene.remove_edge_item(e["id"])

    # ------------------------------------------------------------------------
    # 子图导航
    # ------------------------------------------------------------------------

    def enter_subgraph(self, node_id):
        node = self._find_node_by_id(node_id)
        if not node:
            return
        defn = get_node_def(node["type"])
        if not defn or not defn.get("isSubgraph"):
            return
        if "subgraph" not in node:
            node["subgraph"] = {"nodes": [], "edges": []}
        self.subgraph_path.append(node_id)
        self.reload_canvas()
        self.console.append(f"进入子图: {node.get('title', defn['label'])}", "info")

    def exit_subgraph(self):
        if self.subgraph_path:
            self.subgraph_path.pop()
            self.reload_canvas()

    def navigate_to(self, index):
        if index < 0:
            self.subgraph_path = []
        elif index < len(self.subgraph_path):
            self.subgraph_path = self.subgraph_path[:index + 1]
        self.reload_canvas()

    # ------------------------------------------------------------------------
    # 运行
    # ------------------------------------------------------------------------

    def run_workflow(self):
        if self.subgraph_path:
            self.console.append("请在顶层画布运行工作流 (使用面包屑返回顶层)", "error")
            return

        self.console.append("▶ 开始执行工作流...", "info")
        self._clear_runtime_status()

        def log_callback(value):
            self.console.append(py_str(value), "log")

        try:
            result = run_workflow(self.document["nodes"], self.document["edges"], log_callback)
            if result.errors:
                for err in result.errors:
                    node = next((n for n in self.document["nodes"] if n["id"] == err["nodeId"]), None)
                    name = node.get("title") or (get_node_def(node["type"])["label"] if node and get_node_def(node["type"]) else err["nodeId"]) if node else err["nodeId"]
                    self.console.append(f"节点 {name}: {err['message']}", "error")
            else:
                self.console.append(f"✓ 执行完成 ({len(result.execution_order)} 个节点)", "info")
        except Exception as e:
            self.console.append(f"运行时错误: {e}", "error")
            traceback.print_exc()

        # 刷新画布以显示运行状态
        self.scene.invalidate()
        # 刷新属性面板
        if self.selected_node_id:
            self.properties.show_node(self.selected_node_id)

    def _clear_runtime_status(self):
        def clear_nodes(nodes):
            for n in nodes:
                n["_runtime"] = {"status": "idle"}
                if "subgraph" in n:
                    clear_nodes(n["subgraph"]["nodes"])
        clear_nodes(self.document["nodes"])

    # ------------------------------------------------------------------------
    # 代码生成
    # ------------------------------------------------------------------------

    def generate_code(self):
        code = generate_python(self.document["nodes"], self.document["edges"])
        dlg = CodeGenDialog(code, self)
        dlg.exec_()

    # ------------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------------

    def export_document(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出工作流", "workflow.pyflow", "PyFlow Files (*.pyflow);;JSON Files (*.json)")
        if path:
            # 清除运行时状态
            doc = {"format_version": 1, "nodes": self._clean_nodes(self.document["nodes"]), "edges": self.document["edges"]}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
            self.console.append("✓ 工作流已导出", "info")

    def _clean_nodes(self, nodes):
        result = []
        for n in nodes:
            clean = {k: v for k, v in n.items() if not k.startswith("_")}
            if "subgraph" in clean:
                clean["subgraph"] = {
                    "nodes": self._clean_nodes(clean["subgraph"]["nodes"]),
                    "edges": clean["subgraph"]["edges"],
                }
            result.append(clean)
        return result

    def import_document(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入工作流", "", "PyFlow Files (*.pyflow);;JSON Files (*.json)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                if "nodes" not in doc or "edges" not in doc:
                    raise Exception("无效的 .pyflow 文件")
                self.load_document(doc)
                self.console.append(f"✓ 已加载工作流 ({len(doc['nodes'])} 节点, {len(doc['edges'])} 连线)", "info")
            except Exception as e:
                self.console.append(f"导入失败: {e}", "error")

    def load_document(self, doc):
        self.document = {"format_version": 1, "nodes": doc.get("nodes", []), "edges": doc.get("edges", [])}
        self.subgraph_path = []
        self.reload_canvas()

    def clear_canvas(self):
        reply = QMessageBox.question(self, "确认", "确定要清空当前画布吗?")
        if reply == QMessageBox.Yes:
            nodes, edges = self._deep_get_current_container()
            nodes.clear()
            edges.clear()
            self.reload_canvas()
            self.console.append("画布已清空", "info")

    # ------------------------------------------------------------------------
    # 示例菜单
    # ------------------------------------------------------------------------

    def _show_examples_menu(self):
        menu = QMenu(self)
        for key, ex in EXAMPLES.items():
            action = menu.addAction(f"{ex['name']}  —  {ex['description']}")
            action.triggered.connect(lambda checked, k=key: self._load_example(k))
        btn = self.sender()
        if isinstance(btn, QAction):
            btn.setParent(self)
        menu.exec_(QCursor.pos())

    def _load_example(self, key):
        ex = EXAMPLES[key]
        import copy
        self.load_document(copy.deepcopy(ex))
        self.console.append(f"✓ 已加载示例: {ex['name']}", "info")


# ============================================================================
# 入口
# ============================================================================

def main():
    register_builtin_nodes()
    app = QApplication(sys.argv)
    app.setApplicationName("PyFlowCode")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
