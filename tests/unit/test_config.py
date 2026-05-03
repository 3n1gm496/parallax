def test_settings_import():
    from parallax.config import Settings
    assert Settings.model_fields["friction_bps"].default == 50
    assert Settings.model_fields["compiler_min_confidence"].default == 0.5
    assert Settings.model_fields["semantic_min_relation_confidence"].default == 0.7
    assert Settings.model_fields["court_max_composite_risk"].default == 0.4
    assert Settings.model_fields["kalshi_max_events_per_poll"].default == 50
    assert Settings.model_fields["pipeline_max_open_markets"].default == 0
    assert Settings.model_fields["api_docs_enabled"].default is False
    assert Settings.model_fields["api_auth_token"].default == ""
    assert Settings.model_fields["api_require_auth_for_reads"].default is False


def test_settings_prefers_dotenv_secret_when_shell_value_is_redacted(monkeypatch, tmp_path):
    from parallax.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-real-key-1234567890\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-...")

    settings = Settings()

    assert settings.anthropic_api_key == "sk-ant-real-key-1234567890"
