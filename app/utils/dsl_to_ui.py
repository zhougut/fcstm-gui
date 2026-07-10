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
        Tuple[StateMachine, str, List]: (解析后的状态机对象, 变量定义字符串， 强制转移)
        
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

def parse_forced_transition_line(line: str) -> Tuple[str, str, str, str, str]:
    """
    解析强制转移行，提取源状态、目标状态、事件、条件、操作
    
    Args:
        line: 强制转移行，如 "! * -> Idle : if [a >= 20];" 或 "! Idle -> InService : if [a >= 30];"
        
    Returns:
        Tuple[str, str, str, str, str]: (源状态, 目标状态, 事件, 条件, 操作)
    """
    import re
    
    # 初始化返回值
    source_state = ""
    target_state = ""
    event = ""
    condition = ""
    action = ""
    
    # 移除开头的感叹号和空格
    line = line.lstrip('! ').strip()
    
    # 解析基本格式: source -> target : event [condition] effect { action }
    # 首先分离 source -> target 部分
    if '->' in line:
        parts = line.split('->', 1)
        source_part = parts[0].strip()
        rest_part = parts[1].strip()
        
        # 处理源状态
        if source_part == '*':
            source_state = "! *"
        else:
            source_state = "! " + source_part
        
        # 解析剩余部分 - 需要区分 :: 和 :
        # 先检查是否有 ::
        if '::' in rest_part:
            # 使用 :: 语法
            target_and_rest = rest_part.split('::', 1)
            target_state = target_and_rest[0].strip()
            event_and_rest = target_and_rest[1].strip()
            
            # 提取事件名（在 if 或 effect 或 分号之前）
            event_part = event_and_rest
            if ' if ' in event_part:
                event_part = event_part.split(' if ')[0].strip()
            elif ' effect ' in event_part:
                event_part = event_part.split(' effect ')[0].strip()
            elif ';' in event_part:
                event_part = event_part.split(';')[0].strip()
            else:
                event_part = event_part.rstrip(';').strip()
            
            # 保留原始的:: 前缀格式
            if event_part:
                event = f":: {event_part}"
                
        elif ':' in rest_part:
            # 使用 : 语法
            target_and_rest = rest_part.split(':', 1)
            target_state = target_and_rest[0].strip()
            condition_and_action = target_and_rest[1].strip()
            
            # 检查是否有事件（不是直接以if开头）
            if not condition_and_action.startswith('if'):
                # 提取事件名（在 if 或 effect 或 分号之前）
                event_part = condition_and_action
                if ' if ' in event_part:
                    event_part = event_part.split(' if ')[0].strip()
                elif ' effect ' in event_part:
                    event_part = event_part.split(' effect ')[0].strip()
                elif ';' in event_part:
                    event_part = event_part.split(';')[0].strip()
                else:
                    event_part = event_part.rstrip(';').strip()
                
                # 保留原始的: 前缀格式
                if event_part and not event_part.startswith('if'):
                    event = f": {event_part}"
        else:
            # 没有冒号，直接是目标状态
            if ';' in rest_part:
                target_state = rest_part.rstrip(';').strip()
            else:
                target_state = rest_part.strip()
        
        # 解析条件和操作
        condition_and_action = rest_part
        if '::' in condition_and_action:
            condition_and_action = condition_and_action.split('::', 1)[1]
        elif ':' in condition_and_action:
            condition_and_action = condition_and_action.split(':', 1)[1]
        
        # 提取条件
        if ' if ' in condition_and_action:
            condition_match = re.search(r'if\s*\[(.*?)\]', condition_and_action)
            if condition_match:
                condition = condition_match.group(1)
        
        # 提取操作（在effect之后）
        if 'effect' in condition_and_action:
            effect_part = condition_and_action.split('effect', 1)[1].strip()
            if effect_part.startswith('{') and effect_part.endswith('}'):
                action = effect_part[1:-1].strip()
            else:
                action = effect_part.rstrip(';').strip()
    
    return source_state, target_state, event, condition, action

def convert_fcstm_state_to_my_state(fcstm_state: State, parent_state: Optional[MyState] = None) -> MyState:
    """
    将pyfcstm的State对象转换为自定义的MyState对象，转移和生命周期信息转为结构化数据
    """
    transitions_list = []
    lifecycle_list = []

    # 转移格式化 - 解析转移信息为结构化数据
    if fcstm_state.transitions is not None:
        for cur_transition in fcstm_state.transitions:
            # 提取源状态信息
            source_state = ""
            if hasattr(cur_transition, 'from_state'):
                from_state = cur_transition.from_state
                if isinstance(from_state, str):
                    source_state = from_state
                elif hasattr(from_state, 'mark'):  # _StateSingletonMark类型
                    if from_state.mark == 'INIT_STATE':
                        source_state = "[*]"
                    else:
                        source_state = str(from_state)
                else:
                    source_state = str(from_state)
            
            # 提取目标状态信息
            target_state = ""
            if hasattr(cur_transition, 'to_state'):
                to_state = cur_transition.to_state
                if isinstance(to_state, str):
                    target_state = to_state
                elif hasattr(to_state, 'mark'):  # _StateSingletonMark类型
                    if to_state.mark == 'EXIT_STATE':
                        target_state = "[*]"
                    else:
                        target_state = str(to_state)
                else:
                    target_state = str(to_state)
            
            # 提取事件信息 - 使用AST节点方法获取正确的前缀格式
            event = ""
            if hasattr(cur_transition, 'event') and cur_transition.event:
                try:
                    # 将转移转换为AST节点
                    ast_node = fcstm_state.transition_to_ast_node(cur_transition)
                    
                    # 仿照AST节点的__str__方法提取事件部分
                    if ast_node.event_id is not None:
                        if not ast_node.event_id.is_absolute and \
                                ((ast_node.from_state is not None and hasattr(ast_node.from_state, 'mark') and ast_node.from_state.mark == 'INIT_STATE' and len(ast_node.event_id.path) == 1) or
                                 (ast_node.from_state is not None and not hasattr(ast_node.from_state, 'mark') and len(ast_node.event_id.path) == 2 and
                                  ast_node.event_id.path[0] == ast_node.from_state)):
                            event = f":: {ast_node.event_id.path[-1]}"
                        else:
                            event = f": {ast_node.event_id}"
                except:
                    # 如果AST方法失败，回退到原始方法
                    if hasattr(cur_transition.event, 'name'):
                        event = cur_transition.event.name
                    else:
                        event = str(cur_transition.event)
            
            # 提取条件信息
            condition = ""
            if hasattr(cur_transition, 'guard') and cur_transition.guard:
                condition = str(cur_transition.guard)
            
            # 提取操作信息
            action = ""
            if hasattr(cur_transition, 'effects') and cur_transition.effects:
                action_parts = []
                for effect in cur_transition.effects:
                    if hasattr(effect, 'var_name') and hasattr(effect, 'expr'):
                        action_parts.append(f"{effect.var_name} = {effect.expr}")
                    else:
                        action_parts.append(str(effect))
                action = "; ".join(action_parts)

            transitions_list.append({
                "source": source_state,
                "target": target_state,
                "event": event,
                "condition": condition,
                "action": action
            })

    # 生命周期格式化 - 解析生命周期信息为结构化数据
    def parse_lifecycle_item(stage: str, item):
        aspect = getattr(item, 'aspect', None)
        name = getattr(item, 'name', None)
        is_abstract = getattr(item, 'is_abstract', False)
        doc = getattr(item, 'doc', None)
        operations = getattr(item, 'operations', [])
        
        # 分离类型和是否抽象
        lifecycle_type = stage
        if aspect:
            lifecycle_type += f" {aspect}"
        
        lifecycle_name = name or ""
        
        # 解析操作
        action_parts = []
        for op in operations:
            if hasattr(op, 'var_name') and hasattr(op, 'expr'):
                action_parts.append(f"{op.var_name} = {op.expr}")
        action = "; ".join(action_parts)
        
        # 处理注释信息
        comment = ""
        if is_abstract and doc:
            # 格式化注释，保持原有的缩进格式
            formatted_doc = "\n".join("    " + line.strip() for line in doc.split("\n"))
            comment = f"/*\n{formatted_doc}\n    */"
        
        return {
            "type": lifecycle_type,
            "name": lifecycle_name,
            "action": action,
            "is_abstract": is_abstract,  # 存储布尔值
            "comment": comment
        }

    for item in fcstm_state.on_enters:
        lifecycle_list.append(parse_lifecycle_item("enter", item))

    for item in fcstm_state.on_durings:
        lifecycle_list.append(parse_lifecycle_item("during", item))

    for item in fcstm_state.on_exits:
        lifecycle_list.append(parse_lifecycle_item("exit", item))

    for item in fcstm_state.on_during_aspects:
        lifecycle_list.append(parse_lifecycle_item("during", item))

    my_state = MyState(
        name=fcstm_state.name,
        transitions=transitions_list,
        lifecycle=lifecycle_list,
        parent=parent_state,
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
    # 创建一个映射，从fcstm状态ID到MyState（使用id()获取对象的唯一标识符）
    fcstm_to_my_state = {}
    root_state = None
    
    # 首先创建所有状态对象，但不设置父子关系
    for fcstm_state in state_machine.walk_states():
        my_state = convert_fcstm_state_to_my_state(fcstm_state, None)
        fcstm_to_my_state[id(fcstm_state)] = my_state
        if fcstm_state == state_machine.root_state:
            root_state = my_state

    # 然后设置父子关系
    for fcstm_state in state_machine.walk_states():
        my_state = fcstm_to_my_state[id(fcstm_state)]
        if fcstm_state.parent:
            parent_my_state = fcstm_to_my_state[id(fcstm_state.parent)]
            parent_my_state.add_child(my_state)

    # 创建StateManager
    state_manager = StateManager(root_state)
    
    # 设置变量定义
    state_manager.variable_definitions = variable_definitions
    
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
                # 使用状态路径搜索状态
                forced_state = state_manager.get_state_by_path(forced_item['state'])
                if forced_state is not None:
                    # 解析forced transition为结构化数据
                    forced_transition_lines = forced_item['block'].splitlines()
                    for line in forced_transition_lines:
                        line = line.strip()
                        if line and not line.startswith('//'):
                            # 解析强制转移行，提取更详细的信息
                            source_state, target_state, event, condition, action = parse_forced_transition_line(line)
                            
                            forced_state.transitions.append({
                                "source": source_state or forced_state.get_full_path(),
                                "target": target_state,
                                "event": event,
                                "condition": condition,
                                "action": action
                            })

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
        
        # 递归添加子状态 - 现在直接使用State对象的children列表
        for child_state in state.children:
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
