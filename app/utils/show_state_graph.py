from pyfcstm.model import parse_dsl_node_to_state_machine
from pyfcstm.dsl import parse_with_grammar_entry
from plantumlcli import LocalPlantuml

from ..model import StateManager
from ..config import PLANTUML_JAR_PATH
from ..utils.ui_to_dsl import state_manager_to_dsl


class ShowStateGraph:

    @classmethod
    def show_state_graph(cls, state_manager: StateManager, png_file):
        dsl_str = state_manager_to_dsl(state_manager)
        ast_node = parse_with_grammar_entry(dsl_str, entry_name='state_machine_dsl')
        model = parse_dsl_node_to_state_machine(ast_node)

        # 生成 PlantUML 代码
        plantuml_code = model.to_plantuml()
        local = LocalPlantuml.autoload(plantuml=PLANTUML_JAR_PATH)
        local.dump(png_file, 'png', plantuml_code)