from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import os
from pathlib import Path

from ..model import StateManager
from .ui_to_dsl import state_manager_to_dsl
from pyfcstm.dsl import parse_with_grammar_entry
from pyfcstm.model import parse_dsl_node_to_state_machine

def center_text_in_cell(cell):
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

def export_statechart_to_word(state_manager: StateManager, file_path: str):
    """
    将状态机信息导出为Word文档
    Args:
        state_manager: 状态管理器对象
        file_path: 导出文件路径
    """
    # 1. StateManager转DSL
    dsl_content = state_manager_to_dsl(state_manager)
    # 2. DSL转StateMachine
    ast_node = parse_with_grammar_entry(dsl_content, entry_name='state_machine_dsl')
    state_machine = parse_dsl_node_to_state_machine(ast_node)
    # 3. 创建Word文档
    doc = Document()
    # 状态机整体信息表格
    table = doc.add_table(rows=4, cols=2)
    table.style = 'Table Grid'
    table.cell(0, 0).text = "状态机名称"
    table.cell(0, 1).text = Path(file_path).stem
    table.cell(1, 0).text = "变量定义"
    var_defs = state_manager.variable_definitions
    table.cell(1, 1).text = var_defs
    table.cell(2, 0).text = "状态数"
    table.cell(2, 1).text = str(len(list(state_machine.walk_states())))
    table.cell(3, 0).text = "转移数"
    trans_count = sum(len(s.transitions) for s in state_machine.walk_states() if s.transitions)
    table.cell(3, 1).text = str(trans_count)
    for row in table.rows:
        for cell in row.cells:
            center_text_in_cell(cell)
    doc.add_paragraph()
    # 每个状态单独一个表格
    for state in state_machine.walk_states():
        s_table = doc.add_table(rows=8, cols=2)
        s_table.style = 'Table Grid'
        s_table.cell(0, 0).text = "状态名称"
        s_table.cell(0, 1).text = state.name
        s_table.cell(1, 0).text = "父状态"
        state_parent = state_manager.get_state(state.name).parent
        s_table.cell(1, 1).text = state_parent if state_parent is not None else "无"
        s_table.cell(2, 0).text = "子状态数"
        s_table.cell(2, 1).text = str(len(state.substate_name_to_id))
        s_table.cell(3, 0).text = "类型"
        s_table.cell(3, 1).text = "复合状态" if len(state.substate_name_to_id) > 0 else "简单状态"
        # 生命周期
        s_table.cell(4, 0).text = "进入(enter)"
        s_table.cell(4, 1).text = '\n'.join(
            [f"abstract {e.name}" if getattr(e, 'is_abstract', False) else '\n'.join(f"{op.var_name} = {op.expr}" for op in getattr(e, 'operations', [])) for e in getattr(state, 'on_enters', [])]
        )
        s_table.cell(5, 0).text = "执行中(during)"
        s_table.cell(5, 1).text = '\n'.join(
            [f"abstract {d.name}" if getattr(d, 'is_abstract', False) else '\n'.join(f"{op.var_name} = {op.expr}" for op in getattr(d, 'operations', [])) for d in getattr(state, 'on_durings', [])]
        )
        s_table.cell(6, 0).text = "退出(exit)"
        s_table.cell(6, 1).text = '\n'.join(
            [f"abstract {x.name}" if getattr(x, 'is_abstract', False) else '\n'.join(f"{op.var_name} = {op.expr}" for op in getattr(x, 'operations', [])) for x in getattr(state, 'on_exits', [])]
        )
        # 转移
        s_table.cell(7, 0).text = "转移"
        transitions = state_manager.get_state(state.name).transition
        '''
        if getattr(state, 'transitions', None):
            for t in state.transitions:
                t_str = f"{t.from_state} -> {t.to_state}"
                if t.event: t_str += f" : {t.event.name}"
                if t.guard: t_str += f" if [{t.guard}]"
                if t.effects:
                    t_str += " effect { " + '; '.join(f"{op.var_name} = {op.expr}" for op in t.effects) + " }"
                transitions.append(t_str)'''
        s_table.cell(7, 1).text = transitions
        for row in s_table.rows:
            for cell in row.cells:
                center_text_in_cell(cell)
        doc.add_paragraph()
    doc.save(file_path)
