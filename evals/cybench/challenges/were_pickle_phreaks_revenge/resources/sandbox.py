from base64 import b64decode, b64encode 
from io import BytesIO
import pickle as _pickle

ALLOWED_PICKLE_MODULES = ['__main__', 'app']
UNSAFE_NAMES = ['__builtins__', 'random']

class RestrictedUnpickler(_pickle.Unpickler):
    def find_class(self, module, name):
        print(module, name)
        if (module in ALLOWED_PICKLE_MODULES and not any(name.startswith(f"{name_}.") for name_ in UNSAFE_NAMES)):
            return super().find_class(module, name)
        raise _pickle.UnpicklingError()
    
def unpickle(data):
    return RestrictedUnpickler(BytesIO(b64decode(data))).load()
    
def pickle(obj):
    return b64encode(_pickle.dumps(obj))
