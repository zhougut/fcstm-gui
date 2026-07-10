from ..model import State, StateManager

def format_lifecycle_item(lifecycle_item, indent=0):
    """
    将生命周期项转换为DSL格式字符串
    lifecycle_item: {"type": "enter", "name": "name", "action": "action", "is_abstract": bool, "comment": "注释"}
    """
    if not lifecycle_item:
        return ""
    
    lifecycle_type = lifecycle_item.get("type", "")
    lifecycle_name = lifecycle_item.get("name", "")
    action = lifecycle_item.get("action", "")
    is_abstract = lifecycle_item.get("is_abstract", False)  # 直接使用布尔值
    comment = lifecycle_item.get("comment", "")
    
    ind = '    ' * indent
    
    result = lifecycle_type
    
    # 添加abstract标记
    if is_abstract:
        result += " abstract"
    
    # 添加名称（如果有的话）
    if lifecycle_name:
        result += f" {lifecycle_name}"
    
    # 处理抽象生命周期
    if is_abstract:
        if comment:
            # 处理多行注释的缩进
            if '\n' in comment:
                comment_lines = comment.split('\n')
                formatted_comment = comment_lines[0]  # 第一行保持原样
                for line in comment_lines[1:]:
                    if line.strip():  # 只处理非空行
                        formatted_comment += f"\n{ind}{line.strip()}"
                    else:
                        formatted_comment += "\n"
                result += f" {formatted_comment}"
            else:
                result += f" {comment}"
        result += ";"
    else:
        # 处理非抽象生命周期
        if action:
            result += " {\n"
            # 将action按分号分割，每个操作一行
            actions = [a.strip() for a in action.split(";") if a.strip()]
            for act in actions:
                result += f"{ind}    {act};\n"
            result += f"{ind}}}"
        else:
            result += " {}"
    
    return result

def format_transition_item(transition_item, indent=0):
    """
    将转移项转换为DSL格式字符串
    transition_item: {"source": "source", "target": "target", "event": "event", "condition": "condition", "action": "action"}
    """
    if not transition_item:
        return ""
    
    source = transition_item.get("source", "")
    target = transition_item.get("target", "")
    event = transition_item.get("event", "")
    condition = transition_item.get("condition", "")
    action = transition_item.get("action", "")
    
    ind = '    ' * indent
    
    # 构建转移字符串
    result = ""
    if source and target:
        is_event = False
        result = f"{source} -> {target}"
        if event:
            is_event = True
            # 直接使用存储的事件格式，不进行自动判断
            if event.startswith('::') or event.startswith(':'):
                # 事件已经包含前缀，直接使用
                result += f" {event}"
            else:
                # 事件没有前缀，默认使用 : 前缀
                result += f" : {event}"
        if condition:
            if not is_event:
                result += " :"
            result += f" if [{condition}]"
        if action:
            result += f" effect {{\n"
            # 将action按分号分割，每个操作一行
            actions = [a.strip() for a in action.split(";") if a.strip()]
            for act in actions:
                result += f"{ind}    {act};\n"
            result += f"{ind}}}"
    elif action:
        # 如果只有action，可能是forced transition
        result = action
    
    return result

def format_state(state, lines, state_manager: StateManager, indent=0):
    ind = '    ' * indent
    # 叶子状态
    if not state.children:
        if state.lifecycle or state.transitions:
            lines.append(f"{ind}state {state.name} {{")
            # 转移
            if state.transitions:
                for transition_item in state.transitions:
                    transition_line = format_transition_item(transition_item, indent + 1)
                    if transition_line.strip():
                        lines.append(f"{ind}    {transition_line};")
            # 生命周期
            if state.lifecycle:
                for lifecycle_item in state.lifecycle:
                    lifecycle_line = format_lifecycle_item(lifecycle_item, indent + 1)
                    if lifecycle_line.strip():
                        lines.append(f"{ind}    {lifecycle_line}")
            lines.append(f"{ind}}}")
        else:
            lines.append(f"{ind}state {state.name};")
    else:
        lines.append(f"{ind}state {state.name} {{")
        # 子状态 - 现在直接使用State对象的children列表
        for child in state.children:
            format_state(child, lines, state_manager, indent + 1)
        # 转移
        if state.transitions:
            for transition_item in state.transitions:
                transition_line = format_transition_item(transition_item, indent + 1)
                if transition_line.strip():
                    lines.append(f"{ind}    {transition_line};")
        # 生命周期
        if state.lifecycle:
            for lifecycle_item in state.lifecycle:
                lifecycle_line = format_lifecycle_item(lifecycle_item, indent + 1)
                if lifecycle_line.strip():
                    lines.append(f"{ind}    {lifecycle_line}")
        lines.append(f"{ind}}}")

def state_manager_to_dsl(state_manager: StateManager) -> str:
    """
    将 StateManager 导出为 DSL
    """
    lines = []
    # 变量定义
    if state_manager.variable_definitions:
        for line in state_manager.variable_definitions.split('\n'):
            if line.strip():
                lines.append(line.strip())
        #lines.append('')  # 空行分隔
    # 根状态
    root_state = state_manager.get_root_state()
    if root_state:
        format_state(root_state, lines, state_manager, 0)
    return '\n'.join(lines)


