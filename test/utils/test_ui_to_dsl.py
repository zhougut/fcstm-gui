import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app.model import State, StateManager
from app.utils.ui_to_dsl import state_manager_to_dsl
from app.utils.dsl_to_ui import dsl_to_state_manager


class TestUiToDsl(unittest.TestCase):
    def test_state_manager_to_dsl_simple(self):
        """测试简单的StateManager转换为DSL"""
        root_state = State(
            name="TestMachine",
            transitions=[
                {"source": "[*]", "target": "Idle", "event": "", "condition": "", "action": ""},
                {"source": "Idle", "target": "Active", "event": "", "condition": "start_flag == 1", "action": ""},
                {"source": "Active", "target": "Idle", "event": "", "condition": "stop_flag == 1", "action": ""},
            ],
        )
        state_manager = StateManager(root_state)
        
        # 添加子状态
        idle_state = State(
            name="Idle",
            lifecycle=[{
                "type": "enter",
                "name": "",
                "action": "count = 0",
                "is_abstract": False,
                "comment": "",
            }],
        )
        state_manager.add_state(root_state, idle_state)
        
        active_state = State(
            name="Active",
            transitions=[
                {"source": "[*]", "target": "Running", "event": "", "condition": "", "action": ""},
                {"source": "Running", "target": "Paused", "event": "", "condition": "count > 10", "action": ""},
            ],
        )
        state_manager.add_state(root_state, active_state)

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
        root_state = State(
            name="TrafficLight",
            transitions=[
                {"source": "[*]", "target": "InService", "event": "", "condition": "", "action": ""},
                {"source": "InService", "target": "Idle", "event": ": Maintain", "condition": "", "action": ""},
                {"source": "Idle", "target": "[*]", "event": "", "condition": "", "action": ""},
                {"source": "! *", "target": "Idle", "event": "", "condition": "a >= 20", "action": ""},
            ],
        )
        state_manager = StateManager(root_state)
        
        # 添加InService状态
        in_service = State(
            name="InService",
            transitions=[
                {"source": "[*]", "target": "Red", "event": ": Start", "condition": "", "action": "b = 1"},
                {"source": "Red", "target": "Green", "event": "", "condition": "", "action": "b = 3"},
                {"source": "Green", "target": "Yellow", "event": "", "condition": "", "action": "b = 2"},
                {"source": "Yellow", "target": "Red", "event": "", "condition": "a >= 10", "action": "b = 1; round_count = round_count + 1"},
            ],
            lifecycle=[
                {
                    "type": "enter",
                    "name": "",
                    "action": "a = 0; b = 0; round_count = 0",
                    "is_abstract": False,
                    "comment": "",
                },
                {
                    "type": "enter",
                    "name": "InServiceAbstractEnter",
                    "action": "",
                    "is_abstract": True,
                    "comment": "/* Abstract Operation */",
                },
            ],
        )
        state_manager.add_state(root_state, in_service)
        
        # 添加Red状态
        red_state = State(
            name="Red",
            lifecycle=[{
                "type": "during",
                "name": "",
                "action": "a = 1 << 2",
                "is_abstract": False,
                "comment": "",
            }],
        )
        state_manager.add_state(in_service, red_state)
        
        # 添加Yellow和Green状态
        yellow_state = State(name="Yellow")
        green_state = State(name="Green")
        state_manager.add_state(in_service, yellow_state)
        state_manager.add_state(in_service, green_state)

        idle_state = State(name="Idle")
        state_manager.add_state(root_state, idle_state)

        state_manager.variable_definitions = "def int a = 0;\ndef int b = 0x0;\ndef int round_count = 0;"
        
        # 转换为DSL
        dsl_content = state_manager_to_dsl(state_manager)

        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name
        
        try:
            new_state_manager = dsl_to_state_manager(temp_path)
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
            self.assertIn("InService -> Idle : Maintain;", new_dsl_content)
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
