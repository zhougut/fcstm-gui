import unittest
import sys
import os
import tempfile

# 添加项目根目录到路径，以便导入app模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app.utils.dsl_to_ui import dsl_to_state_manager, parse_fcstm_file, convert_state_machine_to_state_manager
from app.utils.ui_to_dsl import state_manager_to_dsl
from app.model import State, StateManager


class TestDslToUi(unittest.TestCase):
    def test_parse_fcstm_file(self):
        """测试解析fcstm文件功能"""
        dsl_content = """
def int a = 0;
def int b = 0x0;
state Test {
    state Child;
    [*] -> Child;
}
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name
        
        try:
            state_machine, variable_definitions, forced = parse_fcstm_file(temp_path)

            self.assertIsNotNone(state_machine)
            self.assertEqual(state_machine.root_state.name, "Test")
            self.assertEqual(len(state_machine.root_state.substates), 1)
            self.assertEqual(state_machine.root_state.substates['Child'].name, "Child")

            self.assertEqual(variable_definitions, "def int a = 0;\ndef int b = 0x0;")

            self.assertEqual(len(forced), 0)
            
        finally:
            os.unlink(temp_path)

    def test_convert_state_machine_to_state_manager(self):
        """测试将StateMachine转换为StateManager功能"""
        dsl_content = """
def int a = 0;
state Test {
    state Child {
        enter {
            a = 1;
        }
    }
    [*] -> Child;
}
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name
        
        try:
            state_machine, variable_definitions, forced = parse_fcstm_file(temp_path)

            state_manager = convert_state_machine_to_state_manager(state_machine, variable_definitions)

            self.assertIsNotNone(state_manager)
            self.assertEqual(state_manager.root_state.name, "Test")
            self.assertEqual(len(state_manager.root_state.children), 1)

            child_state = state_manager.get_state("Child")
            self.assertIsNotNone(child_state)
            self.assertEqual(child_state.name, "Child")
            self.assertIs(child_state.parent, state_manager.root_state)
            self.assertEqual(child_state.lifecycle, [{
                "type": "enter",
                "name": "",
                "action": "a = 1",
                "is_abstract": False,
                "comment": "",
            }])

            self.assertEqual(state_manager.variable_definitions, "def int a = 0;")
        finally:
            os.unlink(temp_path)

    def test_forced_transitions(self):
        """测试强制转移的处理"""
        dsl_content = """
def int a = 0;
state Test {
    state A;
    state B;
    [*] -> A;
    ! * -> B : if [a >= 10];
}
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name
        
        try:
            state_manager = dsl_to_state_manager(temp_path)
            
            # 验证强制转移被正确添加
            root_state = state_manager.get_root_state()
            self.assertIn({
                "source": "! *",
                "target": "B",
                "event": "",
                "condition": "a >= 10",
                "action": "",
            }, root_state.transitions)
            
        finally:
            os.unlink(temp_path)

    def test_local_event_scope_is_preserved(self):
        dsl_content = """
state Root {
    state A;
    state B;
    [*] -> A;
    A -> B :: Go;
}
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name

        try:
            state_manager = dsl_to_state_manager(temp_path)
            transition = next(
                item for item in state_manager.root_state.transitions
                if item["source"] == "A" and item["target"] == "B"
            )
            self.assertEqual(transition["event"], ":: Go")
        finally:
            os.unlink(temp_path)

    def test_complex_state_machine(self):
        """测试复杂状态机的转换"""
        dsl_content = """
def int a = 0;
def int b = 0x0;
def int round_count = 0;
state TrafficLight {
    state InService {
        enter {
            a = 0;
            b = 0;
            round_count = 0;
        }
        enter abstract InServiceAbstractEnter /*
            Abstract Operation When Entering State 'InService'
            TODO: Should be Implemented In Generated Code Framework
        */
        state Red {
            during {
                a = 0x1 << 2;
            }
        }
        state Yellow;
        state Green;
        [*] -> Red :: Start effect {
            b = 0x1;
        }
        Red -> Green effect {
            b = 0x3;
        }
        Green -> Yellow effect {
            b = 0x2;
        }
        Yellow -> Red : if [a >= 10] effect {
            b = 0x1;
            round_count = round_count + 1;
        }
    }
    state Idle;
    [*] -> InService;
    InService -> Idle :: Maintain;
    Idle -> [*];
    ! * -> Idle : if [a >= 20];
}
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(dsl_content)
            temp_path = temp.name
        
        try:
            # 解析并转换
            state_manager = dsl_to_state_manager(temp_path)
            
            # 验证根状态
            root_state = state_manager.get_root_state()
            self.assertEqual(root_state.name, "TrafficLight")
            self.assertEqual(len(root_state.children), 2)
            
            # 验证InService状态
            in_service = state_manager.get_state("InService")
            self.assertIsNotNone(in_service)
            self.assertIs(in_service.parent, root_state)
            self.assertEqual(len(in_service.children), 3)
            
            # 验证Red状态
            red_state = state_manager.get_state("Red")
            self.assertIsNotNone(red_state)
            self.assertIs(red_state.parent, in_service)
            self.assertEqual(red_state.lifecycle, [{
                "type": "during",
                "name": "",
                "action": "a = 1 << 2",
                "is_abstract": False,
                "comment": "",
            }])
            
            # 验证Yellow和Green状态
            yellow_state = state_manager.get_state("Yellow")
            green_state = state_manager.get_state("Green")
            self.assertIsNotNone(yellow_state)
            self.assertIsNotNone(green_state)
            
            # 验证Idle状态
            idle_state = state_manager.get_state("Idle")
            self.assertIsNotNone(idle_state)
            self.assertIs(idle_state.parent, root_state)
            
            # 验证根状态的转移
            root_edges = {
                (item["source"], item["target"]): item
                for item in root_state.transitions
            }
            self.assertEqual(root_edges[("[*]", "InService")]["event"], "")
            self.assertEqual(root_edges[("InService", "Idle")]["event"], ":: Maintain")
            self.assertIn(("Idle", "[*]"), root_edges)
            self.assertEqual(root_edges[("! *", "Idle")]["condition"], "a >= 20")
            
            # 验证InService状态的转移
            service_edges = {
                (item["source"], item["target"]): item
                for item in in_service.transitions
            }
            self.assertEqual(service_edges[("[*]", "Red")]["event"], ":: Start")
            self.assertEqual(service_edges[("[*]", "Red")]["action"], "b = 1")
            self.assertEqual(service_edges[("Red", "Green")]["action"], "b = 3")
            
            # 验证InService状态的生命周期
            concrete_enter, abstract_enter = in_service.lifecycle
            self.assertEqual(
                concrete_enter["action"],
                "a = 0; b = 0; round_count = 0",
            )
            self.assertTrue(abstract_enter["is_abstract"])
            self.assertEqual(abstract_enter["name"], "InServiceAbstractEnter")
            
            # 验证变量定义
            self.assertEqual(state_manager.variable_definitions, "def int a = 0;\ndef int b = 0x0;\ndef int round_count = 0;")

            dsl_output = state_manager_to_dsl(state_manager)

            # 检查关键部分是否在输出DSL中存在
            self.assertIn("def int a = 0;", dsl_output)
            self.assertIn("def int b = 0x0;", dsl_output)
            self.assertIn("state TrafficLight {", dsl_output)
            self.assertIn("state InService {", dsl_output)
            self.assertIn("enter {", dsl_output)
            self.assertIn("a = 0;", dsl_output)
            self.assertIn("enter abstract InServiceAbstractEnter", dsl_output)
            self.assertIn("[*] -> InService;", dsl_output)
            self.assertIn("! * -> Idle : if [a >= 20];", dsl_output)
            
        finally:
            os.unlink(temp_path)

    def test_broken_dsl(self):
        """测试错误的DSL内容处理"""
        broken_dsl = """
def int a = 0;
state Test {
    state Child
    [*] -> Child;
}
"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.fcstm') as temp:
            temp.write(broken_dsl)
            temp_path = temp.name
        
        try:
            with self.assertRaises(Exception) as context:
                dsl_to_state_manager(temp_path)

            self.assertIn("解析fcstm文件失败", str(context.exception))
            
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
