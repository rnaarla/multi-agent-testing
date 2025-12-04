import yaml
def load_yaml(file):
    return yaml.safe_load(file.file.read())
