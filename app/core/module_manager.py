class ModuleManager:
    def __init__(self):
        self._modules = []

    def register_module(self, title, view_class):
        self._modules.append({
            "title": title,
            "view_class": view_class
        })

    def get_registered_modules(self):
        return self._modules