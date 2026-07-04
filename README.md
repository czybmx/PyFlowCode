# PyFlowCode
A python tools that generated with AI (Non-Professional)

=================

🚀 PyFlowCode — 节点式 Python 代码可视化编辑器
=================

不仅是一个工具，更是一份 PySide6 图形界面编程的【绝佳教程】。
像 ComfyUI 或虚幻引擎蓝图一样，通过拖拽节点和连线编写 Python 代码。

✨ 本版本针对新手体验进行了深度优化 (升华点)：
  1. 🚀 快捷搜索：在画布空白处【右键】或按【Tab】键，像 VSCode 一样秒加节点。
  2. ✨ 一键排版：拯救“面条图”，点击工具栏“整理画布”自动对齐节点。
  3. 🛡️ 连线防呆：类型不匹配时明确报错，不再默默失败。
  4. 📝 注释节点：支持在画布上做笔记，理清编程思路。
  5. 💾 自动保存：再也不怕手滑关掉窗口，心血白费 (启动时自动恢复草稿)。
  6. 🧲 磁吸连线：扩大端口判定范围，连线更轻松。

🛠️ 【开发者指南：如何添加你自己的节点？】
  1. 找到 `register_builtin_nodes()` 函数。
  2. 模仿 `_make_binary_op` 或直接调用 `register_node({...})`。
  3. 定义 `inputs` (输入端口), `outputs` (输出端口)。
  4. 编写 `execute` (运行时逻辑) 和 `to_code` (生成 Python 代码的逻辑)。
  5. 重启程序，你的节点就会出现在左侧面板和搜索框中！

运行方式:
    python pyfc.py

依赖:
    PySide6 (若未安装会自动安装)



------------------------------------



=================

🚀 PyFlowCode — Node-Based Python Code Visual Editor
=================

More than just a tool, it's an [excellent tutorial] for PySide6 GUI programming.
Write Python code by dragging and dropping nodes and connecting wires, just like ComfyUI or Unreal Engine Blueprints.

✨ This version features deep optimizations for the beginner experience (Key Upgrades):
  1. 🚀 Quick Search: [Right-click] on an empty canvas area or press [Tab] to add nodes instantly, just like in VSCode.
  2. ✨ One-Click Layout: Rescue your "spaghetti graphs"! Click "Organize Canvas" in the toolbar to auto-align nodes.
  3. 🛡️ Foolproof Wiring: Get clear error messages for type mismatches instead of silent failures.
  4. 📝 Comment Nodes: Take notes directly on the canvas to clarify your programming logic.
  5. 💾 Auto-Save: Never worry about accidentally closing the window and losing your hard work (drafts are auto-restored on startup).
  6. 🧲 Magnetic Wiring: Expanded port hit areas make connecting wires a breeze.

🛠️ [Developer Guide: How to Add Your Own Nodes?]
  1. Locate the `register_builtin_nodes()` function.
  2. Mimic `_make_binary_op` or directly call `register_node({...})`.
  3. Define `inputs` (input ports) and `outputs` (output ports).
  4. Implement `execute` (runtime logic) and `to_code` (Python code generation logic).
  5. Restart the program, and your nodes will appear in the left panel and the search box!

How to Run:
    python pyfc.py

Dependencies:
    PySide6 (will be auto-installed if missing)
