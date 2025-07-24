from typing import List, Dict, Optional

__all__ = [
    'State',
    'StateManager',
]

class State:
    """
    用于描述状态机中单个状态的数据结构。

    State类包含状态名、转移、生命周期、父状态名和子状态名列表等信息。
    可用于状态机的建模、管理和序列化。

    :param name: 状态名
    :type name: str
    :param transition: 状态的转移描述
    :type transition: str
    :param lifecycle: 状态的生命周期描述
    :type lifecycle: str
    :param parent: 父状态名（如无父状态则为None）
    :type parent: str | None
    :param children: 子状态名列表
    :type children: List[str] | None
    """

    def __init__(self, name: str, transition: str = '', lifecycle: str = '',
                 parent: Optional[str] = None, children: Optional[List[str]] = None):
        self.name = name
        self.transition = transition
        self.lifecycle = lifecycle
        self.parent = parent
        self.children = children if children is not None else []

    def __repr__(self):
        return f"State(name={self.name}, transition={self.transition}, lifecycle={self.lifecycle}, parent={self.parent}, children={self.children})"

class StateManager:
    """
    用于管理和操作多个State对象的管理器。

    StateManager支持添加、获取、删除、重命名状态，以及获取初始状态和所有状态列表。
    适用于状态机的整体管理和批量操作。

    :param root_state: 初始状态对象（可选）
    :type root_state: State | None
    """
    def __init__(self, root_state: Optional[State] = None):
        self.states: Dict[str, State] = {}
        self.root_state = root_state
        self.variable_definitions: str = ""  # 变量定义字符串
        if root_state is not None:
            self.states[root_state.name] = root_state

    def add_state(self, father_state: Optional[State], state: State):
        self.states[state.name] = state
        if father_state is not None:
            # 设置父子关系
            state.parent = father_state.name
            if state.name not in father_state.children:
                father_state.children.append(state.name)

    def get_state(self, name: str) -> Optional[State]:
        return self.states.get(name)

    def remove_state(self, name: str, visited=None):
        if visited is None:
            visited = set()
        if name not in self.states or name in visited:
            return
        visited.add(name)
        state = self.states[name]
        for child_name in list(state.children):
            self.remove_state(child_name, visited)
        del self.states[name]

    def get_root_state(self) -> Optional[State]:
        return self.root_state

    def get_all_states(self) -> List[State]:
        return list(self.states.values())

    def rename_state(self, old_name: str, new_name: str):
        if old_name not in self.states:
            raise ValueError(f"状态名 '{old_name}' 不存在。")
        if new_name in self.states:
            raise ValueError(f"状态名 '{new_name}' 已存在。")
        state = self.states.pop(old_name)
        state.name = new_name
        self.states[new_name] = state

        for s in self.states.values():
            if s.parent == old_name:
                s.parent = new_name
            s.children = [new_name if child == old_name else child for child in s.children]

        if self.root_state and self.root_state.name == old_name:
            self.root_state = state
