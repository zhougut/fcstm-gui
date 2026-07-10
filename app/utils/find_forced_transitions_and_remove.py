import re
import os

def find_and_remove_forced_transitions(text):
    """
    从文本中识别以! 开头的强制转移块，并获取该强制转移块所在的状态路径，然后删除该强制转移块
    
    Args:
        text (str): 包含状态机定义的文本
        
    Returns:
        tuple: (强制转移列表, 删除强制转移后的文本)
        强制转移列表中每项包含：
        - 'state': 状态的完整路径（如 'TrafficLight.InService'）
        - 'block': 强制转移的代码块
    """
    # 用于存储结果
    forced_transitions = []
    
    # 解析文本，构建状态树和行映射
    lines = text.splitlines()
    state_tree, line_to_state = parse_state_structure(lines)
    
    # 识别强制转移
    i = 0
    n = len(lines)
    output_lines = []
    
    while i < n:
        line = lines[i]
        # 检查是否为强制转移
        if re.match(r'^\s*!\s*.*->.*', line):
            # 获取当前行所在的状态
            current_state = line_to_state.get(i)
            
            # 判断是否为多行 effect 块
            if '{' in line and line.rstrip().endswith('{'):
                # 多行 effect 块
                block_lines = [line]
                block_brace_level = 1
                start_i = i
                i += 1
                
                while i < n and block_brace_level > 0:
                    l2 = lines[i]
                    block_lines.append(l2)
                    block_brace_level += l2.count('{')
                    block_brace_level -= l2.count('}')
                    i += 1
                
                forced_transitions.append({
                    'state': current_state,
                    'block': '\n'.join(block_lines)
                })
            else:
                # 单行强制转移
                forced_transitions.append({
                    'state': current_state,
                    'block': line
                })
                i += 1
            # 不加入 output_lines（即删除）
            continue
        
        # 正常加入输出
        output_lines.append(line)
        i += 1
    
    return forced_transitions, '\n'.join(output_lines)

def parse_state_structure(lines):
    """
    解析状态机结构，构建状态树和行到状态路径的映射
    
    Args:
        lines (list): 文本行列表
        
    Returns:
        tuple: (状态树, 行号到状态路径的映射)
    """
    state_stack = []
    line_to_state = {}  # 映射行号到状态路径
    state_tree = {}  # 状态树结构
    
    # 跟踪大括号嵌套层级
    brace_stack = []
    
    for i, line in enumerate(lines):
        # 检查是否为状态定义行
        state_match = re.match(r'^\s*state\s+(\w+)\s*{', line)
        if state_match:
            state_name = state_match.group(1)
            state_stack.append(state_name)
            brace_stack.append('state')
        
        # 记录当前行所在的状态路径
        if state_stack:
            # 构建状态路径，用点号分隔
            state_path = '.'.join(state_stack)
            line_to_state[i] = state_path
        
        # 检查大括号开始（非状态定义）
        if '{' in line:
            brace_count = line.count('{')
            # 如果这行已经被识别为状态定义，则第一个大括号已经计入
            if state_match:
                brace_count -= 1
            
            # 添加其他大括号到栈
            for _ in range(brace_count):
                brace_stack.append('other')
        
        # 检查大括号结束
        if '}' in line:
            for _ in range(line.count('}')):
                if brace_stack:
                    brace_type = brace_stack.pop()
                    if brace_type == 'state' and state_stack:
                        state_stack.pop()
    
    return state_tree, line_to_state
