import unittest
from app.model.model import State, StateManager


class TestStateAndStateManager(unittest.TestCase):
    def test_state_creation_and_repr(self):
        child_state = State(name="B")
        transitions = [{
            "source": "A",
            "target": "B",
            "event": "",
            "condition": "",
            "action": "",
        }]
        lifecycle = [{
            "type": "enter",
            "name": "",
            "action": "x = 1",
            "is_abstract": False,
            "comment": "",
        }]
        s = State(
            name="A",
            transitions=transitions,
            lifecycle=lifecycle,
            children=[child_state],
        )
        self.assertEqual(s.name, "A")
        self.assertEqual(s.transitions, transitions)
        self.assertEqual(s.lifecycle, lifecycle)
        self.assertIsNone(s.parent)
        self.assertEqual(s.children, [child_state])
        self.assertIn("State(name=A", repr(s))

    def test_add_and_get_state(self):
        root = State("Root")
        sm = StateManager(root)
        s1 = State("S1")
        sm.add_state(root, s1)
        self.assertEqual(sm.get_state("S1"), s1)
        self.assertIn(s1, root.children)
        self.assertEqual(s1.parent, root)

    def test_remove_state(self):
        root = State("Root")
        sm = StateManager(root)
        s1 = State("S1")
        s2 = State("S2")
        sm.add_state(root, s1)
        sm.add_state(s1, s2)
        sm.remove_state(s1)
        self.assertIsNone(sm.get_state("S1"))
        self.assertIsNone(sm.get_state("S2"))
        self.assertEqual(sm.get_state("Root"), root)

    def test_get_root_and_all_states(self):
        root = State("Root")
        sm = StateManager(root)
        s1 = State("S1")
        sm.add_state(root, s1)
        self.assertEqual(sm.get_root_state(), root)
        all_names = {s.name for s in sm.get_all_states()}
        self.assertEqual(all_names, {"Root", "S1"})

    def test_rename_state(self):
        root = State("Root")
        sm = StateManager(root)
        s1 = State("S1")
        sm.add_state(root, s1)
        sm.rename_state(s1, "S1_new")
        self.assertIsNone(sm.get_state("S1"))
        self.assertIsNotNone(sm.get_state("S1_new"))
        self.assertIn(s1, root.children)  # s1对象还在，只是名字改了
        self.assertEqual(s1.name, "S1_new")
        self.assertEqual(s1.parent, root)
        # 测试重命名根状态
        sm.rename_state(root, "RootNew")
        self.assertEqual(sm.get_root_state().name, "RootNew")

    def test_variable_definitions(self):
        root = State("Root")
        sm = StateManager(root)
        sm.variable_definitions = "def int a = 0;\ndef int b = 1;"
        self.assertIn("def int a = 0;", sm.variable_definitions)
        self.assertIn("def int b = 1;", sm.variable_definitions)

    def test_remove_state_cycle_protection(self):
        root = State("Root")
        sm = StateManager(root)
        s1 = State("S1")
        s2 = State("S2")
        sm.add_state(root, s1)
        sm.add_state(s1, s2)
        # 手动制造循环（虽然新结构中这不太可能发生）
        s2.children.append(root)
        sm.remove_state(root)
        self.assertIsNone(sm.get_root_state())
        self.assertEqual(sm.states, {})
        self.assertEqual(root.children, [])
        self.assertEqual(s1.children, [])
        self.assertEqual(s2.children, [])
        self.assertIsNone(s1.parent)
        self.assertIsNone(s2.parent)

    def test_remove_cyclic_subtree_does_not_remove_root(self):
        root = State("Root")
        sm = StateManager(root)
        child = State("Child")
        grandchild = State("Grandchild")
        sm.add_state(root, child)
        sm.add_state(child, grandchild)
        # A malformed owning back edge must not pull the root into the subtree
        # being removed or leave the retained root pointing at removed data.
        grandchild.add_child(root)

        sm.remove_state(child)

        self.assertIs(sm.get_root_state(), root)
        self.assertEqual(sm.get_all_states(), [root])
        self.assertIsNone(root.parent)
        self.assertEqual(root.children, [])
        self.assertIsNone(child.parent)
        self.assertEqual(child.children, [])
        self.assertIsNone(grandchild.parent)
        self.assertEqual(grandchild.children, [])

if __name__ == "__main__":
    unittest.main()
