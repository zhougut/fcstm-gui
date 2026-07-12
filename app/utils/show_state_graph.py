from pyfcstm.model import parse_dsl_node_to_state_machine
from pyfcstm.dsl import parse_with_grammar_entry
from app.application.graph_render import GraphRenderService
from ..model import StateManager
from ..config import PLANTUML_JAR_PATH
from ..utils.ui_to_dsl import state_manager_to_dsl


class ShowStateGraph:

    @classmethod
    def show_state_graph(cls, state_manager: StateManager, png_file, model=None):
        if model is None:
            dsl_str = state_manager_to_dsl(state_manager)
            ast_node = parse_with_grammar_entry(dsl_str, entry_name='state_machine_dsl')
            model = parse_dsl_node_to_state_machine(ast_node)

        return GraphRenderService().render(
            model.to_plantuml(),
            png_file,
            'png',
            plantuml_jar=PLANTUML_JAR_PATH,
            overwrite=True,
        )
