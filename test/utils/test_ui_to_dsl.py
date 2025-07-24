import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app.model import State, StateManager
from app.utils.ui_to_dsl import state_manager_to_dsl
from app.utils.dsl_to_ui import parse_fcstm_file, convert_state_machine_to_state_manager


class TestUiToDsl(unittest.TestCase):
    def test_state_manager_to_dsl_simple(self):
        """测试简单的StateManager转换为DSL"""
        root_state = State(name="TestMachine", transition="", lifecycle="", parent=None, children=[])
        state_manager = StateManager(root_state)
        
        # 添加子状态
        idle_state = State(
            name="Idle", 
            transition="", 
            lifecycle="enter {\n    count = 0;\n}", 
            parent="TestMachine", 
            children=[]
        )
        state_manager.add_state(root_state, idle_state)
        
        active_state = State(
            name="Active", 
            transition="[*] -> Running;\nRunning -> Paused : if [count > 10];", 
            lifecycle="", 
            parent="TestMachine", 
            children=[]
        )
        state_manager.add_state(root_state, active_state)

        root_state.transition = "[*] -> Idle;\nIdle -> Active : if [start_flag == 1];\nActive -> Idle : if [stop_flag == 1];"

        state_manager.variable_definitions = "def int count = 0;\ndef int start_flag = 0;\ndef int stop_flag = 0;"

        dsl_content = state_manager_to_dsl(state_manager)

        expected_lines = [
            "def int count = 0;",
            "def int start_flag = 0;",
            "def int stop_flag = 0;",
            "state TestMachine {",
            "    state Idle {",
            "        enter {",
            "            count = 0;",
            "        }",
            "    }",
            "    state Active {",
            "        [*] -> Running;",
            "        Running -> Paused : if [count > 10];",
            "    }",
            "    [*] -> Idle;",
            "    Idle -> Active : if [start_flag == 1];",
            "    Active -> Idle : if [stop_flag == 1];",
            "}"
        ]
        
        expected_dsl = "\n".join(expected_lines)
        self.assertEqual(dsl_content, expected_dsl)
    
    def test_state_manager_to_dsl_complex(self):
        """测试复杂的StateManager转换为DSL，包含嵌套状态和操作"""
        root_state = State(name="TrafficLight", transition="", lifecycle="", parent=None, children=[])
        state_manager = StateManager(root_state)
        
        # 添加InService状态
        in_service = State(
            name="InService", 
            transition="[*] -> Red :: Start effect {\n    b = 0x1;\n}\nRed -> Green effect {\n    b = 0x3;\n}\nGreen -> Yellow effect {\n    b = 0x2;\n}\nYellow -> Red : if [a >= 10] effect {\n    b = 0x1;\n    round_count = round_count + 1;\n}", 
            lifecycle="enter {\n    a = 0;\n    b = 0;\n    round_count = 0;\n}\nenter abstract InServiceAbstractEnter /*\n    Abstract Operation When Entering State 'InService'\n    TODO: Should be Implemented In Generated Code Framework\n*/", 
            parent="TrafficLight", 
            children=[]
        )
        state_manager.add_state(root_state, in_service)
        
        # 添加Red状态
        red_state = State(
            name="Red", 
            transition="", 
            lifecycle="during {\n    a = 0x1 << 2;\n}", 
            parent="InService", 
            children=[]
        )
        state_manager.add_state(in_service, red_state)
        
        # 添加Yellow和Green状态
        yellow_state = State(name="Yellow", transition="", lifecycle="", parent="InService", children=[])
        green_state = State(name="Green", transition="", lifecycle="", parent="InService", children=[])
        state_manager.add_state(in_service, yellow_state)
        state_manager.add_state(in_service, green_state)

        idle_state = State(name="Idle", transition="", lifecycle="", parent="TrafficLight", children=[])
        state_manager.add_state(root_state, idle_state)

        root_state.transition = "[*] -> InService;\nInService -> Idle :: Maintain;\nIdle -> [*];\n! * -> Idle : if [a >= 20];"

        state_manager.variable_definitions = "def int a = 0;\ndef int b = 0x0;\ndef int round_count = 0;"
        
        # 转换为DSL
        dsl_content = state_manager_to_dsl(state_manager)

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name
        
        try:
            state_machine, variable_definitions, forced = parse_fcstm_file(temp_path)

            new_state_manager = convert_state_machine_to_state_manager(state_machine, variable_definitions)

            new_dsl_content = state_manager_to_dsl(new_state_manager)

            if len(forced) > 0:
                for forced_item in forced:
                    forced_state = new_state_manager.get_state(forced_item['state'])
                    if forced_state:
                        # 清理前导空格
                        cleaned_lines = [line.lstrip() for line in forced_item['block'].splitlines()]
                        forced_transition = '\n'.join(cleaned_lines)
                        forced_state.transition += f'\n{forced_transition}'

                new_dsl_content = state_manager_to_dsl(new_state_manager)

            self.assertIn("def int a = 0;", new_dsl_content)
            self.assertIn("def int b = 0x0;", new_dsl_content)
            self.assertIn("def int round_count = 0;", new_dsl_content)
            
            # 验证状态结构
            self.assertIn("state TrafficLight {", new_dsl_content)
            self.assertIn("state InService {", new_dsl_content)
            self.assertIn("state Red {", new_dsl_content)
            self.assertIn("state Yellow;", new_dsl_content)
            self.assertIn("state Green;", new_dsl_content)
            self.assertIn("state Idle;", new_dsl_content)
            
            # 验证转移
            self.assertIn("[*] -> InService;", new_dsl_content)
            self.assertIn("InService -> Idle :: Maintain;", new_dsl_content)
            self.assertIn("Idle -> [*];", new_dsl_content)
            self.assertIn("! * -> Idle : if [a >= 20];", new_dsl_content)
            
            # 验证生命周期
            self.assertIn("during {", new_dsl_content)
            self.assertIn("a = 1 << 2;", new_dsl_content)
            self.assertIn("enter {", new_dsl_content)
            self.assertIn("a = 0;", new_dsl_content)
            self.assertIn("b = 0;", new_dsl_content)
            self.assertIn("round_count = 0;", new_dsl_content)
            
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
