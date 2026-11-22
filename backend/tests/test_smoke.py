def test_app_package_importable():
    import app.api.main  # noqa: F401
    import app.pipeline  # noqa: F401
