from scripts import verify_generated_templates


def test_generated_python_template_executes_real_lifecycle(tmp_path):
    model = verify_generated_templates.load_state_machine_from_text(
        verify_generated_templates.SOURCE
    )
    target = tmp_path / "python"
    verify_generated_templates.GenerationService().generate(
        model, str(target), template_name="python"
    )

    verify_generated_templates._verify_python(target)
