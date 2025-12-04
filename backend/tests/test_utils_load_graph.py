import io

from app.utils.load_graph import load_yaml


def test_load_yaml_parses_uploaded_file():
    class DummyUpload:
        def __init__(self, payload: bytes):
            self.file = io.BytesIO(payload)

    data = b"foo: bar\nvalue: 1\n"
    obj = load_yaml(DummyUpload(data))
    assert obj == {"foo": "bar", "value": 1}
