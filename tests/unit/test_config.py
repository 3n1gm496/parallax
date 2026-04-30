def test_settings_import():
    from parallax.config import Settings
    assert Settings.model_fields["friction_bps"].default == 50
