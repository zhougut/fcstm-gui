from ..model import State as MyState, StateManager
from pyfcstm.model import *
from pyfcstm.dsl import parse_with_grammar_entry
from pyfcstm.dsl.node import TransitionDefinition
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from typing import List, Optional, Tuple
from .find_forced_transitions_and_remove import find_and_remove_forced_transitions


def parse_fcstm_file(file_path: str) -> Tuple[StateMachine, str, List]:
    """
    解析fcstm文件并返回StateMachine对象和变量定义
    
    Args:
        file_path: fcstm文件路径
        
    Returns:
        Tuple[StateMachine, str, List]: (解析后的状态机对象, 变量定义字符串)
        
    Raises:
        Exception: 解析失败时抛出异常
    """
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            dsl_content = f.read()
        #先解析一遍，判断是否有问题
        pre_ast_node = parse_with_grammar_entry(dsl_content, entry_name='state_machine_dsl')
        _ = parse_dsl_node_to_state_machine(pre_ast_node)

        forced, new_dsl_content = find_and_remove_forced_transitions(dsl_content)
        # 提取变量定义
        variable_definitions = extract_variable_definitions(new_dsl_content)
        
        # 使用fcstm库解析DSL内容
        ast_node = parse_with_grammar_entry(new_dsl_content, entry_name='state_machine_dsl')
        state_machine = parse_dsl_node_to_state_machine(ast_node)

        return state_machine, variable_definitions, forced
    except Exception as e:
        raise Exception(f"解析fcstm文件失败: {str(e)}")


def extract_variable_definitions(dsl_content: str) -> str:
    """
    从DSL内容中提取变量定义
    
    Args:
        dsl_content: DSL文件内容
        
    Returns:
        str: 变量定义字符串
    """
    variable_lines = []
    lines = dsl_content.split('\n')
    
    for line in lines:
        line = line.strip()
        # 匹配以 "def " 开头的变量定义行
        if line.startswith('def '):
            variable_lines.append(line)
    
    return '\n'.join(variable_lines)

def convert_fcstm_state_to_my_state(fcstm_state: State, parent_name: Optional[str] = None) -> MyState:
    """
    将pyfcstm的State对象转换为自定义的MyState对象，转移和生命周期信息转为字符串
    """
    transition_info = []
    lifecycle_info = []

    # 转移格式化 - 使用 to_transition_ast_node 方法转换为 TransitionDefinition
    if fcstm_state.transitions is not None:
        for cur_transition in fcstm_state.transitions:
            # 将转移转换为 TransitionDefinition 对象
            transition_def = fcstm_state.to_transition_ast_node(cur_transition)
            # 使用 __str__ 方法获取字符串表示
            transition_str = str(transition_def)
            transition_info.append(transition_str)

    # 生命周期
    def format_onstage(stage: str, item) -> str:
        aspect = getattr(item, 'aspect', None)
        name = getattr(item, 'name', None)
        doc = getattr(item, 'doc', None)
        is_abstract = getattr(item, 'is_abstract', False)
        operations = getattr(item, 'operations', [])
        cur_str = stage
        if aspect:
            cur_str += f" {aspect}"
        if is_abstract:
            cur_str += " abstract"
        if name:
            cur_str += f" {name}"
        if is_abstract:
            if doc:
                # 将doc按行分割，每行前面添加tab，然后重新组合
                formatted_doc = "\n".join("    " + line for line in doc.split("\n"))
                cur_str += f" /*\n{formatted_doc}\n*/"
            cur_str += ";"
        else:
            cur_str += " {\n"
            for op in operations:
                expr_str = op.expr
                cur_str += f"    {op.var_name} = {expr_str};\n"
            cur_str += "}"
        return cur_str

    for item in fcstm_state.on_enters:
        lifecycle_info.append(format_onstage("enter", item))

    for item in fcstm_state.on_durings:
        lifecycle_info.append(format_onstage("during", item))

    for item in fcstm_state.on_exits:
        lifecycle_info.append(format_onstage("exit", item))

    for item in fcstm_state.on_during_aspects:
        lifecycle_info.append(format_onstage(">> during", item))

    my_state = MyState(
        name=fcstm_state.name,
        transition='\n'.join(transition_info),
        lifecycle='\n'.join(lifecycle_info),
        parent=parent_name,
        children=[]
    )
    return my_state


def convert_state_machine_to_state_manager(state_machine: StateMachine, variable_definitions: str = "") -> StateManager:
    """
    将fcstm的StateMachine对象转换为StateManager对象
    
    Args:
        state_machine: fcstm的StateMachine对象
        variable_definitions: 变量定义字符串
        
    Returns:
        StateManager: 转换后的StateManager对象
    """
    all_state: List[MyState] = []
    root_state = None
    for fcstm_state in state_machine.walk_states():
        # 确定父状态名称
        parent_name = None
        if fcstm_state.parent:
            parent_name = fcstm_state.parent.name
        
        # 转换状态
        my_state = convert_fcstm_state_to_my_state(fcstm_state, parent_name)
        all_state.append(my_state)
        if fcstm_state == state_machine.root_state:
            root_state = my_state

    # 创建StateManager
    state_manager = StateManager(root_state)
    
    # 设置变量定义
    state_manager.variable_definitions = variable_definitions
    
    # 添加所有状态到StateManager
    for cur_state in all_state:
        if cur_state.name != root_state.name:  # 根状态已经在StateManager中
            parent_state = None
            if cur_state.parent is not None:
                parent_state = state_manager.get_state(cur_state.parent)

            state_manager.add_state(parent_state, cur_state)
    
    return state_manager


def dsl_to_state_manager(file_path: str) -> StateManager:
    """
    将DSL文件转换为StateManager对象
    
    Args:
        file_path: fcstm文件路径
        
    Returns:
        StateManager: StateManager对象
        
    Raises:
        Exception: 转换失败时抛出异常
    """
    try:
        # 解析fcstm文件
        state_machine, variable_definitions, forced = parse_fcstm_file(file_path)

        # 转换为StateManager
        state_manager = convert_state_machine_to_state_manager(state_machine, variable_definitions)

        if len(forced) > 0:
            for forced_item in forced:
                forced_state = state_manager.get_state(forced_item['state'])
                # 去除每行前导空格
                forced_transition_lines = forced_item['block'].splitlines()
                # 处理每一行，去掉前导空格
                cleaned_lines = []
                for line in forced_transition_lines:
                    cleaned_lines.append(line.lstrip())
                forced_transition = '\n'.join(cleaned_lines)
                forced_state.transition += f'\n{forced_transition}'

        return state_manager
        
    except Exception as e:
        raise Exception(f"DSL到StateManager转换失败: {str(e)}")


def update_ui_from_state_manager(main_window, state_manager: StateManager):
    """
    使用StateManager更新UI界面
    
    Args:
        main_window: 主窗口对象
        state_manager: StateManager对象
    """
    # 更新变量定义
    main_window.edit_var_def.setPlainText(state_manager.variable_definitions)
    
    # 清空树形控件
    main_window.tree_all_state.clear()
    
    # 添加状态到树形控件
    def add_state_to_tree(state: MyState, parent_item=None):
        item = QtWidgets.QTreeWidgetItem([state.name])
        item.setData(0, Qt.UserRole, state)
        
        if parent_item:
            parent_item.addChild(item)
        else:
            main_window.tree_all_state.addTopLevelItem(item)
        
        # 递归添加子状态
        for child_name in state.children:
            child_state = state_manager.get_state(child_name)
            if child_state:
                add_state_to_tree(child_state, item)
    
    # 从根状态开始添加
    if state_manager.root_state:
        add_state_to_tree(state_manager.root_state)
    
    # 展开所有节点
    main_window.tree_all_state.expandAll()

    # 切换到状态机详情页面
    if main_window.at_page_initial:
        main_window.stackedWidget_state_machine.setCurrentIndex(1)
        main_window.at_page_initial = False
