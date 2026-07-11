from typing import List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Self

__all__ = [
    'State',
    'StateManager',
]

class State:
    """
    用于描述状态机中单个状态的数据结构。

    State类包含状态名、转移、生命周期、父状态引用和子状态引用列表等信息。
    可用于状态机的建模、管理和序列化。

    :param name: 状态名
    :type name: str
    :param transitions: 状态的转移列表，每项包含源状态、目标状态、事件、条件、操作
    :type transitions: List[Dict[str, str]]
    :param lifecycle: 状态的生命周期列表，每项包含类型、名称、操作、是否抽象、注释
    :type lifecycle: List[Dict[str, str]]
    :param parent: 父状态引用（如无父状态则为None）
    :type parent: Optional['State']
    :param children: 子状态引用列表
    :type children: List['State']
    """

    def __init__(self, name: str, transitions: Optional[List[Dict[str, str]]] = None, 
                 lifecycle: Optional[List[Dict[str, str]]] = None,
                 parent: Optional['State'] = None, children: Optional[List['State']] = None,
                 source_ref=None):
        self.name = name
        self.transitions = transitions if transitions is not None else []
        self.lifecycle = lifecycle if lifecycle is not None else []
        self.parent = parent
        self.children = children if children is not None else []
        self.source_ref = source_ref

    def __repr__(self):
        parent_name = self.parent.name if self.parent else None
        children_names = [child.name for child in self.children]
        return f"State(name={self.name}, transitions={self.transitions}, lifecycle={self.lifecycle}, parent={parent_name}, children={children_names})"
    
    def get_full_path(self) -> str:
        """
        获取状态的完整路径，用于唯一标识状态
        """
        if self.parent is None:
            return self.name
        return f"{self.parent.get_full_path()}.{self.name}"
    
    def find_child_by_name(self, name: str) -> Optional['State']:
        """
        在当前状态的直接子状态中查找指定名称的状态
        """
        for child in self.children:
            if child.name == name:
                return child
        return None
    
    def add_child(self, child: 'State'):
        """
        添加子状态
        """
        if child not in self.children:
            self.children.append(child)
            child.parent = self
    
    def remove_child(self, child: 'State'):
        """
        移除子状态
        """
        if child in self.children:
            self.children.remove(child)
            child.parent = None

class StateManager:
    """
    用于管理和操作多个State对象的管理器。

    StateManager支持添加、获取、删除、重命名状态，以及获取初始状态和所有状态列表。
    现在支持层次结构，同一父状态下的子状态名称不能重复。

    :param root_state: 初始状态对象（可选）
    :type root_state: State | None
    """
    def __init__(self, root_state: Optional[State] = None):
        self.states: Dict[str, State] = {}  # 保留以保持向后兼容，但不再作为主要存储
        self.root_state = root_state
        self.variable_definitions: str = ""  # 变量定义字符串
        if root_state is not None:
            self._rebuild_states_dict()

    def add_state(self, father_state: Optional[State], state: State):
        """
        添加状态到状态管理器
        现在检查同一父状态下的子状态名称是否重复
        """
        if father_state is not None:
            # 检查同一父状态下是否已有同名子状态
            if father_state.find_child_by_name(state.name) is not None:
                raise ValueError(f"状态 '{father_state.name}' 下已存在名为 '{state.name}' 的子状态")
            father_state.add_child(state)
        else:
            # 检查是否已有根状态
            if self.root_state is not None and self.root_state != state:
                raise ValueError("状态机中只能有一个根状态")
        
        self._rebuild_states_dict()

    def get_state(self, name: str, parent: Optional[State] = None) -> Optional[State]:
        """
        根据名称查找状态
        如果指定了parent，则在该父状态下查找
        否则在整个状态树中查找第一个匹配的状态
        """
        if parent is not None:
            return parent.find_child_by_name(name)
        
        # 在整个状态树中查找
        def _search_state(current_state: State, target_name: str) -> Optional[State]:
            if current_state.name == target_name:
                return current_state
            for child in current_state.children:
                result = _search_state(child, target_name)
                if result is not None:
                    return result
            return None
        
        if self.root_state is not None:
            return _search_state(self.root_state, name)
        return None
    
    def get_state_by_path(self, path: str) -> Optional[State]:
        """
        根据完整路径查找状态
        路径格式: "Root.StateA.StateB"
        """
        if not path or self.root_state is None:
            return None
        
        parts = path.split('.')
        current_state = self.root_state
        
        # 检查根状态名称
        if current_state.name != parts[0]:
            return None
        
        # 逐层查找
        for part in parts[1:]:
            current_state = current_state.find_child_by_name(part)
            if current_state is None:
                return None
        
        return current_state

    def remove_state(self, state: State):
        """
        移除状态及其所有子状态
        """
        removing_root = state is self.root_state
        if removing_root:
            self.root_state = None
        elif state.parent is not None:
            state.parent.remove_child(state)

        # State trees normally cannot contain cycles, but imported or manually
        # mutated data can.  Tear the subtree down iteratively so a malformed
        # back edge cannot recurse forever or pull the retained root into a
        # child-subtree deletion.
        retained_root = self.root_state
        pending = [state]
        visited = set()
        while pending:
            current = pending.pop()
            state_id = id(current)
            if state_id in visited:
                continue
            visited.add(state_id)

            for child in list(current.children):
                if child is retained_root:
                    if retained_root.parent is current:
                        retained_root.parent = None
                    continue
                if child.parent is current:
                    pending.append(child)

            current.children.clear()
            current.parent = None

        self._rebuild_states_dict()

    def get_root_state(self) -> Optional[State]:
        return self.root_state

    def get_all_states(self) -> List[State]:
        """
        获取所有状态的列表
        """
        states = []
        if self.root_state is not None:
            def _collect_states(state: State):
                states.append(state)
                for child in state.children:
                    _collect_states(child)
            _collect_states(self.root_state)
        return states

    def rename_state(self, state: State, new_name: str):
        """
        重命名状态
        检查同一父状态下是否已有同名子状态
        """
        if state.parent is not None:
            # 检查同一父状态下是否已有同名子状态
            existing_sibling = state.parent.find_child_by_name(new_name)
            if existing_sibling is not None and existing_sibling != state:
                raise ValueError(f"状态 '{state.parent.name}' 下已存在名为 '{new_name}' 的子状态")
        
        state.name = new_name
        self._rebuild_states_dict()

    def _rebuild_states_dict(self):
        """
        重建 states 字典（保持向后兼容）
        """
        self.states.clear()
        if self.root_state is not None:
            self._add_to_states_dict(self.root_state)
    
    def _add_to_states_dict(self, state: State):
        """
        递归地将状态添加到 states 字典中
        """
        # 使用完整路径作为键，保证唯一性
        full_path = state.get_full_path()
        self.states[full_path] = state
        # 也使用简单名称作为键（为了向后兼容）
        if state.name not in self.states:
            self.states[state.name] = state
        
        for child in state.children:
            self._add_to_states_dict(child)
