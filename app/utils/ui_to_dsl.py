from ..model import State, StateManager


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

    def format_state(state, indent=0):
        ind = '    ' * indent
        # 叶子状态
        if not state.children:
            if state.lifecycle or state.transition:
                lines.append(f"{ind}state {state.name} {{")
                # 生命周期
                if state.lifecycle:
                    for cur_lifecycle_line in state.lifecycle.split('\n'):
                        if cur_lifecycle_line.strip():
                            lines.append(f"{ind}    {cur_lifecycle_line}")
                # 转移
                if state.transition:
                    for cur_transition_line in state.transition.split('\n'):
                        if cur_transition_line.strip():
                            lines.append(f"{ind}    {cur_transition_line}")
                lines.append(f"{ind}}}")
            else:
                lines.append(f"{ind}state {state.name};")
        else:
            lines.append(f"{ind}state {state.name} {{")
            # 子状态
            for child_name in state.children:
                child = state_manager.get_state(child_name)
                if child:
                    format_state(child, indent + 1)
            # 生命周期
            if state.lifecycle:
                for cur_lifecycle_line in state.lifecycle.split('\n'):
                    if cur_lifecycle_line.strip():
                        lines.append(f"{ind}    {cur_lifecycle_line}")
            # 转移
            if state.transition:
                for cur_transition_line in state.transition.split('\n'):
                    if cur_transition_line.strip():
                        lines.append(f"{ind}    {cur_transition_line}")
            lines.append(f"{ind}}}")

    # 根状态
    root_state = state_manager.get_root_state()
    if root_state:
        format_state(root_state, 0)
    return '\n'.join(lines)


