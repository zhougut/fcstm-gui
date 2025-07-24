import unittest
from app.utils.find_forced_transitions_and_remove import find_and_remove_forced_transitions

class TestFindForcedTransitionsAndRemove(unittest.TestCase):
    def test_single_line_forced_transition(self):
        dsl = """
state A {
    ! * -> B : if [x > 0];
    state B;
}
"""
        forced, new_text = find_and_remove_forced_transitions(dsl)
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0]['state'], 'A')
        self.assertIn('! * -> B : if [x > 0];', forced[0]['block'])
        self.assertNotIn('! * -> B : if [x > 0];', new_text)

    def test_multi_line_forced_transition(self):
        dsl = """
state A {
    ! * -> B : if [x > 0] effect {
        y = 1;
        z = 2;
    }
    state B;
}
"""
        forced, new_text = find_and_remove_forced_transitions(dsl)
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0]['state'], 'A')
        self.assertIn('effect {', forced[0]['block'])
        self.assertNotIn('! * -> B : if [x > 0] effect {', new_text)

    def test_nested_states_and_forced(self):
        dsl = """
state Top {
    state Sub1 {
        ! * -> Sub2 : if [a == 1];
        state Sub2;
    }
    ! * -> Sub1 : if [b == 2];
}
"""
        forced, new_text = find_and_remove_forced_transitions(dsl)
        self.assertEqual(len(forced), 2)
        found = {f['state']: f['block'] for f in forced}
        self.assertIn('Sub1', found)
        self.assertIn('Top', found)
        self.assertIn('! * -> Sub2 : if [a == 1];', found['Sub1'])
        self.assertIn('! * -> Sub1 : if [b == 2];', found['Top'])
        self.assertNotIn('! * -> Sub2 : if [a == 1];', new_text)
        self.assertNotIn('! * -> Sub1 : if [b == 2];', new_text)

    def test_forced_with_various_indents(self):
        dsl = """
state S {
        ! * -> X : if [a];
    ! * -> Y : if [b];
\t! * -> Z : if [c];
}
"""
        forced, new_text = find_and_remove_forced_transitions(dsl)
        self.assertEqual(len(forced), 3)
        for f in forced:
            self.assertTrue(f['block'].strip().startswith('!'))
        self.assertNotIn('! * -> X : if [a];', new_text)
        self.assertNotIn('! * -> Y : if [b];', new_text)
        self.assertNotIn('! * -> Z : if [c];', new_text)

    def test_complex_large_state_machine(self):
        dsl = """
def int a = 0;
def int b = 0;
state Root {
    state A {
        ! * -> B : if [a > 1];
        state B {
            ! * -> C : if [b > 2] effect {
                b = 3;
            }
            state C;
        }
    }
    state D;
    ! * -> D : if [a == 0];
    ! D -> A : if [b == 0] effect {
        a = 1;
    }
}
"""
        forced, new_text = find_and_remove_forced_transitions(dsl)
        self.assertEqual(len(forced), 4)
        found = {(f['state'], f['block'].split('->')[1].split(':')[0].strip()): f['block'] for f in forced}
        self.assertIn(('A', 'B'), found)
        self.assertIn(('B', 'C'), found)
        self.assertIn(('Root', 'D'), found)
        self.assertIn(('Root', 'A'), found)
        for f in forced:
            self.assertTrue(f['block'].lstrip().startswith('!'))
        for f in forced:
            self.assertNotIn(f['block'], new_text)

    def test_no_forced_transition(self):
        dsl = """
state A {
    A -> B : if [x > 0];
    state B;
}
"""
        forced, new_text = find_and_remove_forced_transitions(dsl)
        self.assertEqual(len(forced), 0)
        self.assertIn('A -> B : if [x > 0];', new_text)

if __name__ == "__main__":
    unittest.main()